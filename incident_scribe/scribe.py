"""Core orchestration: parse → extract → synthesize → validate.

All Claude API calls go through this module with retry, rate limiting,
event sourcing, and structured output validation.
"""

from __future__ import annotations

import json
import os
import re

import anthropic
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from .patterns.event_sourcing import ApiTimer, log_api_call
from .prompts import (
    EXTRACT_RETRY,
    EXTRACT_SYSTEM,
    PROMPT_VERSION,
    SYNTHESIZE_RETRY,
    SYNTHESIZE_SYSTEM,
)
from .schema import IncidentEvent, IncidentReport, MessageStream, TimelineEntry

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_RETRIES = 3


def _get_model() -> str:
    return os.environ.get("INCIDENT_SCRIBE_MODEL", DEFAULT_MODEL)


def _get_max_tokens() -> int:
    return int(os.environ.get("INCIDENT_SCRIBE_MAX_TOKENS", "4096"))


def _strip_code_block(text: str) -> str:
    """Remove markdown code fences if present."""
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return m.group(1) if m else text


def _build_message_context(stream: MessageStream) -> str:
    """Format the message stream for the LLM prompt."""
    lines = []
    for msg in stream.messages:
        ts = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        lines.append(f"[{msg.id}] {ts} | {msg.actor}: {msg.text}")
    return "\n".join(lines)


@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=10),
    reraise=True,
)
def _call_claude(
    client: anthropic.Anthropic,
    system: str,
    user_content: str,
    stage: str,
    temperature: float = 0.2,
) -> tuple[str, int, int]:
    """Make a Claude API call with retry, timing, and audit logging."""
    model = _get_model()

    with ApiTimer() as timer:
        response = client.messages.create(
            model=model,
            max_tokens=_get_max_tokens(),
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )

    output_text = response.content[0].text
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    log_api_call(
        stage=stage,
        model=model,
        prompt_version=PROMPT_VERSION,
        input_text=user_content[:500],
        output_text=output_text[:500],
        latency_ms=timer.elapsed_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    return output_text, input_tokens, output_tokens


def extract_events(client: anthropic.Anthropic, stream: MessageStream) -> list[IncidentEvent]:
    """Extract discrete events from the thread. Claude returns message IDs, not timestamps."""
    context = _build_message_context(stream)
    prompt = f"Identify the key incident events in this Slack thread:\n\n{context}"

    for attempt in range(MAX_RETRIES):
        system = EXTRACT_SYSTEM if attempt == 0 else f"{EXTRACT_SYSTEM}\n\n{EXTRACT_RETRY}"
        raw, _, _ = _call_claude(client, system, prompt, stage="extract", temperature=0.2)

        try:
            parsed = json.loads(_strip_code_block(raw))
            events = [IncidentEvent(**e) for e in parsed]
            return events
        except (json.JSONDecodeError, ValidationError):
            if attempt == MAX_RETRIES - 1:
                raise

    return []  # unreachable due to reraise


def synthesize_report(
    client: anthropic.Anthropic,
    stream: MessageStream,
    events: list[IncidentEvent],
) -> IncidentReport:
    """Stage 2: Synthesize a structured report from validated events.

    Timestamps are resolved deterministically from message IDs — the LLM
    never generates timestamps.
    """
    # Build a message ID → timestamp lookup
    ts_lookup = {msg.id: msg.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC") for msg in stream.messages}

    # Build the events context with resolved timestamps
    event_lines = []
    for ev in events:
        ts = ts_lookup.get(ev.message_id, "unknown time")
        event_lines.append(f"- [{ts}] {ev.event_type}: {ev.description}")
    events_text = "\n".join(event_lines)

    context = _build_message_context(stream)
    prompt = (
        f"Validated incident events (with timestamps):\n\n{events_text}\n\n"
        f"Original thread messages:\n\n{context}"
    )

    for attempt in range(MAX_RETRIES):
        system = SYNTHESIZE_SYSTEM if attempt == 0 else f"{SYNTHESIZE_SYSTEM}\n\n{SYNTHESIZE_RETRY}"
        raw, _, _ = _call_claude(client, system, prompt, stage="synthesize", temperature=0.4)

        try:
            parsed = json.loads(_strip_code_block(raw))
            # Normalize timeline entries
            if "timeline" in parsed:
                parsed["timeline"] = [
                    TimelineEntry(time=e.get("time", ""), event=e.get("event", ""))
                    for e in parsed["timeline"]
                ]
            report = IncidentReport(**parsed)
            return report
        except (json.JSONDecodeError, ValidationError):
            if attempt == MAX_RETRIES - 1:
                raise

    raise RuntimeError("Failed to synthesize report after retries")  # unreachable


def generate_report(thread_data: str) -> IncidentReport:
    """Full pipeline: parse → extract → synthesize → validate."""
    from .parser import parse_thread

    stream = parse_thread(thread_data)
    client = anthropic.Anthropic()
    events = extract_events(client, stream)
    report = synthesize_report(client, stream, events)
    return report
