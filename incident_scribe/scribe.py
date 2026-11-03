"""Core orchestration: parse → redact → extract → validate → synthesize → resolve.

The model never produces a timestamp. It cites message IDs; this module checks
every cited ID against the parsed thread and resolves times itself.
"""

from __future__ import annotations

import logging

import anthropic

from .claude import call_structured
from .prompts import EXTRACT_SYSTEM, ID_RETRY, SYNTHESIZE_SYSTEM
from .redact import RedactMode, Redactor
from .schema import (
    ExtractedEvents,
    IncidentEvent,
    IncidentReport,
    MessageStream,
    ReportDraft,
    TimelineEntry,
)

log = logging.getLogger(__name__)

_TS_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


def _build_message_context(stream: MessageStream, redactor: Redactor) -> str:
    """Format the message stream for the LLM prompt, redacting as we go."""
    lines = []
    for msg in stream.messages:
        ts = msg.timestamp.strftime(_TS_FORMAT)
        lines.append(f"[{msg.id}] {ts} | {redactor.redact(msg.actor)}: {redactor.redact(msg.text)}")
    return "\n".join(lines)


def validate_events(
    stream: MessageStream, events: list[IncidentEvent]
) -> tuple[list[IncidentEvent], list[str]]:
    """Split events into (valid, unknown_ids), deduplicated and in thread order."""
    order = {m.id: i for i, m in enumerate(stream.messages)}
    valid: list[IncidentEvent] = []
    unknown: list[str] = []
    seen: set[tuple[str, str]] = set()
    for ev in events:
        if ev.message_id not in order:
            unknown.append(ev.message_id)
            continue
        key = (ev.message_id, ev.event_type)
        if key in seen:
            continue
        seen.add(key)
        valid.append(ev)
    valid.sort(key=lambda e: order[e.message_id])
    return valid, unknown


def extract_events(
    client: anthropic.Anthropic,
    stream: MessageStream,
    redactor: Redactor | None = None,
) -> list[IncidentEvent]:
    """Extract discrete events. Hallucinated message IDs get one corrective retry, then drop."""
    redactor = redactor or Redactor()
    context = _build_message_context(stream, redactor)
    prompt = f"Identify the key incident events in this Slack thread:\n\n{context}"

    result = call_structured(
        client,
        system=EXTRACT_SYSTEM,
        user_content=prompt,
        output_model=ExtractedEvents,
        stage="extract",
    )
    valid, unknown = validate_events(stream, result.events)
    if not unknown:
        return valid

    retry_prompt = f"{prompt}\n\n{ID_RETRY.format(ids=', '.join(sorted(set(unknown))))}"
    result = call_structured(
        client,
        system=EXTRACT_SYSTEM,
        user_content=retry_prompt,
        output_model=ExtractedEvents,
        stage="extract_retry",
    )
    valid, unknown = validate_events(stream, result.events)
    if unknown:
        log.warning("dropping %d event(s) citing unknown message IDs: %s", len(unknown), unknown)
    return valid


def synthesize_report(
    client: anthropic.Anthropic,
    stream: MessageStream,
    events: list[IncidentEvent],
    redactor: Redactor | None = None,
) -> IncidentReport:
    """Write the report. Timeline rows cite message IDs; times are looked up, not generated."""
    redactor = redactor or Redactor()
    ts_lookup = {msg.id: msg.timestamp.strftime(_TS_FORMAT) for msg in stream.messages}

    event_lines = [
        f"- [{ev.message_id}] {ts_lookup[ev.message_id]} {ev.event_type}: "
        f"{redactor.redact(ev.description)}"
        for ev in events
        if ev.message_id in ts_lookup
    ]
    prompt = (
        "Validated incident events (message ID, timestamp, type):\n\n"
        + "\n".join(event_lines)
        + "\n\nOriginal thread messages:\n\n"
        + _build_message_context(stream, redactor)
    )

    draft = call_structured(
        client,
        system=SYNTHESIZE_SYSTEM,
        user_content=prompt,
        output_model=ReportDraft,
        stage="synthesize",
    )

    order = {m.id: i for i, m in enumerate(stream.messages)}
    rows = [row for row in draft.timeline if row.message_id in ts_lookup]
    dropped = len(draft.timeline) - len(rows)
    if dropped:
        log.warning("dropped %d timeline row(s) citing unknown message IDs", dropped)
    rows.sort(key=lambda r: order[r.message_id])

    return IncidentReport(
        summary=draft.summary,
        impact=draft.impact,
        timeline=[TimelineEntry(time=ts_lookup[r.message_id], event=r.event) for r in rows],
        root_cause=draft.root_cause,
        remediation=draft.remediation,
        open_questions=draft.open_questions,
        lessons_learned=draft.lessons_learned,
    )


def generate_report_from_stream(
    stream: MessageStream,
    *,
    redact: RedactMode = "secrets",
    client: anthropic.Anthropic | None = None,
) -> IncidentReport:
    client = client or anthropic.Anthropic()
    redactor = Redactor(mode=redact)
    events = extract_events(client, stream, redactor)
    report = synthesize_report(client, stream, events, redactor)
    if redactor.findings:
        log.info("redacted before sending: %s", redactor.findings)
    return report


def generate_report(
    thread_data: str,
    *,
    redact: RedactMode = "secrets",
    tz: str = "UTC",
    reference_date: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> IncidentReport:
    """Full pipeline from raw thread text (Slack export JSON or pasted text)."""
    from .parser import parse_thread

    stream = parse_thread(thread_data, tz=tz, reference_date=reference_date)
    return generate_report_from_stream(stream, redact=redact, client=client)
