"""Compensating transaction pattern for incident-scribe.

If a downstream post fails (e.g. writing to Confluence or Notion),
the draft is preserved locally so work is never lost.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DRAFTS_DIR = Path(".incident-scribe") / "drafts"


def save_draft(report_text: str, filename: str | None = None) -> Path:
    """Save a report draft to the local drafts directory.

    Returns the path where the draft was saved.
    """
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    if filename is None:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"incident-report-{ts}.md"

    path = DRAFTS_DIR / filename
    path.write_text(report_text)
    return path


def save_draft_json(report_data: dict, filename: str | None = None) -> Path:
    """Save structured report data as JSON."""
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    if filename is None:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"incident-report-{ts}.json"

    path = DRAFTS_DIR / filename
    path.write_text(json.dumps(report_data, indent=2))
    return path
