"""Slack export JSON parsing utilities.

Handles both channel export files and individual thread exports.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..parser import parse_slack_export
from ..schema import MessageStream


def load_slack_export(path: str | Path) -> MessageStream:
    """Load and parse a Slack export JSON file."""
    data = Path(path).read_text()
    return parse_slack_export(data)


def load_slack_thread_from_channel(path: str | Path, thread_ts: str) -> MessageStream:
    """Extract a specific thread from a channel export by thread timestamp."""
    data = json.loads(Path(path).read_text())
    messages = [m for m in data if m.get("thread_ts") == thread_ts or m.get("ts") == thread_ts]
    return parse_slack_export(json.dumps(messages))
