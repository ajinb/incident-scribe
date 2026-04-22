"""Parse Slack threads from export JSON or plain text into a normalized MessageStream.

All timestamp handling happens here — the LLM never touches a clock.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from .schema import Message, MessageStream


def parse_slack_export(data: str) -> MessageStream:
    """Parse a Slack export JSON file into a MessageStream."""
    raw = json.loads(data)
    messages = []

    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and "messages" in raw:
        items = raw["messages"]
    else:
        raise ValueError("Unrecognized Slack export format: expected a list or {messages: [...]}")

    for item in items:
        ts = item.get("ts", "")
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (ValueError, TypeError):
            dt = datetime.now(tz=timezone.utc)

        actor = item.get("user", item.get("username", item.get("bot_id", "unknown")))
        text = item.get("text", "")
        reactions = [r.get("name", "") for r in item.get("reactions", [])]
        thread_ts = item.get("thread_ts")
        parent = thread_ts if thread_ts and thread_ts != ts else None

        messages.append(
            Message(
                id=f"msg-{ts}",
                actor=actor,
                timestamp=dt,
                text=text,
                reactions=reactions,
                thread_parent=parent,
            )
        )

    messages.sort(key=lambda m: m.timestamp)
    return MessageStream(messages=messages, source_type="slack_export")


def parse_plain_text(data: str) -> MessageStream:
    """Parse a copy-pasted Slack thread (plain text) into a MessageStream.

    Expected format (flexible):
        [HH:MM] username: message text
        or
        username  HH:MM AM/PM
        message text
    """
    messages = []
    lines = data.strip().split("\n")

    # Pattern 1: [HH:MM] user: text  or  [YYYY-MM-DD HH:MM] user: text
    pattern_bracket = re.compile(
        r"^\[?(\d{4}-\d{2}-\d{2}\s+)?"
        r"(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)\]?\s+"
        r"([^:]+):\s*(.+)"
    )
    # Pattern 2: user  timestamp\n  text (Slack copy-paste style)
    pattern_slack = re.compile(r"^(\S+)\s+(\d{1,2}:\d{2}\s*[AP]M)")

    i = 0
    base_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        m = pattern_bracket.match(line)
        if m:
            date_part = (m.group(1) or base_date).strip()
            time_part = m.group(2).strip()
            actor = m.group(3).strip()
            text = m.group(4).strip()
            dt = _parse_timestamp(date_part, time_part)
            messages.append(
                Message(
                    id=f"msg-{uuid.uuid4().hex[:8]}",
                    actor=actor,
                    timestamp=dt,
                    text=text,
                )
            )
            i += 1
            continue

        m2 = pattern_slack.match(line)
        if m2:
            actor = m2.group(1)
            time_part = m2.group(2).strip()
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].startswith("  "):
                text_lines.append(lines[i].strip())
                i += 1
            dt = _parse_timestamp(base_date, time_part)
            messages.append(
                Message(
                    id=f"msg-{uuid.uuid4().hex[:8]}",
                    actor=actor,
                    timestamp=dt,
                    text=" ".join(text_lines) if text_lines else line,
                )
            )
            continue

        # Fallback: treat as continuation of previous message or standalone
        if messages:
            messages[-1].text += f" {line}"
        i += 1

    if not messages:
        # Last resort: treat entire input as a single message
        messages.append(
            Message(
                id=f"msg-{uuid.uuid4().hex[:8]}",
                actor="unknown",
                timestamp=datetime.now(tz=timezone.utc),
                text=data.strip(),
            )
        )

    return MessageStream(messages=messages, source_type="plain_text")


def _parse_timestamp(date_str: str, time_str: str) -> datetime:
    """Best-effort timestamp parsing."""
    for fmt in [
        "%Y-%m-%d %I:%M %p",
        "%Y-%m-%d %I:%M%p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]:
        try:
            return datetime.strptime(f"{date_str} {time_str}", fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(tz=timezone.utc)


def parse_thread(data: str) -> MessageStream:
    """Auto-detect format and parse."""
    stripped = data.strip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            return parse_slack_export(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
    return parse_plain_text(stripped)
