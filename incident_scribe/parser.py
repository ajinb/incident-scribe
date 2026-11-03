"""Parse Slack threads from export JSON or plain text into a normalized MessageStream.

All timestamp handling happens here — the LLM never touches a clock. Parsing is
deterministic: the same input, timezone and reference date always produce the
same message IDs and timestamps. Nothing falls back to "now".

* Slack export IDs are ``msg-<ts>``; plain-text IDs are ``msg-0001``, ``msg-0002``…
  in order of appearance.
* Times without a date use ``reference_date`` (default: the date of the first
  dated message, else 1970-01-01 so output is still reproducible). A time that
  goes backwards past midnight (23:58 → 00:03) rolls over to the next day.
* Naive times are interpreted in ``tz`` (an IANA name, default UTC) and stored
  as UTC.
* A line whose time cannot be parsed inherits the previous message's timestamp.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .schema import Message, MessageStream

_EPOCH_DATE = date(1970, 1, 1)


def _zone(tz: str) -> ZoneInfo | timezone:
    return timezone.utc if tz.upper() == "UTC" else ZoneInfo(tz)


def parse_slack_export(data: str) -> MessageStream:
    """Parse a Slack export JSON file (a list, or ``{"messages": [...]}``)."""
    raw = json.loads(data)

    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and "messages" in raw:
        items = raw["messages"]
    else:
        raise ValueError("Unrecognized Slack export format: expected a list or {messages: [...]}")

    messages: list[Message] = []
    previous: datetime | None = None
    for index, item in enumerate(items, start=1):
        ts = str(item.get("ts", ""))
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (ValueError, TypeError, OverflowError):
            dt = previous or datetime.combine(_EPOCH_DATE, time(), tzinfo=timezone.utc)
        previous = dt

        actor = (
            item.get("user_name")
            or item.get("user")
            or item.get("username")
            or item.get("bot_id")
            or "unknown"
        )
        thread_ts = item.get("thread_ts")
        messages.append(
            Message(
                id=f"msg-{ts}" if ts else f"msg-{index:04d}",
                actor=actor,
                timestamp=dt,
                text=item.get("text", ""),
                reactions=[r.get("name", "") for r in item.get("reactions", [])],
                thread_parent=thread_ts if thread_ts and thread_ts != ts else None,
            )
        )

    messages.sort(key=lambda m: m.timestamp)  # stable: equal times keep file order
    return MessageStream(messages=messages, source_type="slack_export")


_PATTERN_BRACKET = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2}\s+)?"
    r"(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?)\]?\s+"
    r"([^:]+):\s*(.+)"
)
_PATTERN_SLACK = re.compile(r"^(\S+)\s+(\d{1,2}:\d{2}\s*[AaPp][Mm])")
_TIME_FORMATS = ("%I:%M %p", "%I:%M%p", "%H:%M:%S", "%H:%M")


def _parse_time(text: str) -> time | None:
    cleaned = text.strip().upper()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
    return None


def parse_plain_text(
    data: str, *, tz: str = "UTC", reference_date: str | None = None
) -> MessageStream:
    """Parse a copy-pasted Slack thread.

    Accepted line shapes (mixed freely)::

        [HH:MM] username: message text
        [YYYY-MM-DD HH:MM] username: message text
        username  HH:MM AM
          indented continuation text
    """
    zone = _zone(tz)
    lines = data.strip().split("\n")

    first_dated = next(
        (
            m.group(1).strip()
            for line in lines
            if (m := _PATTERN_BRACKET.match(line.strip())) and m.group(1)
        ),
        None,
    )
    current_date = date.fromisoformat(reference_date or first_dated or _EPOCH_DATE.isoformat())

    messages: list[Message] = []
    last_local: datetime | None = None

    def _stamp(date_part: str | None, time_part: str) -> datetime:
        nonlocal current_date, last_local
        parsed = _parse_time(time_part)
        if parsed is None:
            return (
                messages[-1].timestamp
                if messages
                else datetime.combine(current_date, time(), tzinfo=zone).astimezone(timezone.utc)
            )
        if date_part:
            current_date = date.fromisoformat(date_part.strip())
            local = datetime.combine(current_date, parsed, tzinfo=zone)
        else:
            local = datetime.combine(current_date, parsed, tzinfo=zone)
            if last_local is not None and local < last_local - timedelta(minutes=1):
                current_date += timedelta(days=1)  # crossed midnight
                local = datetime.combine(current_date, parsed, tzinfo=zone)
        last_local = local
        return local.astimezone(timezone.utc)

    def _add(actor: str, stamp: datetime, text: str) -> None:
        messages.append(
            Message(id=f"msg-{len(messages) + 1:04d}", actor=actor, timestamp=stamp, text=text)
        )

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        m = _PATTERN_BRACKET.match(line)
        if m:
            _add(m.group(3).strip(), _stamp(m.group(1), m.group(2)), m.group(4).strip())
            i += 1
            continue

        m2 = _PATTERN_SLACK.match(line)
        if m2:
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].startswith("  "):
                text_lines.append(lines[i].strip())
                i += 1
            _add(m2.group(1), _stamp(None, m2.group(2)), " ".join(text_lines) or line)
            continue

        if messages:  # continuation of the previous message
            messages[-1].text += f" {line}"
        i += 1

    if not messages:
        _add(
            "unknown",
            datetime.combine(current_date, time(), tzinfo=zone).astimezone(timezone.utc),
            data.strip(),
        )

    return MessageStream(messages=messages, source_type="plain_text")


def parse_thread(data: str, *, tz: str = "UTC", reference_date: str | None = None) -> MessageStream:
    """Auto-detect format and parse."""
    stripped = data.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            return parse_slack_export(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
    return parse_plain_text(stripped, tz=tz, reference_date=reference_date)
