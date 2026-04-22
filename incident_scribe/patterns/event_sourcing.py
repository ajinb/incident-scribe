"""Immutable audit log for every Claude API call.

Every call — input, output, model version, prompt version, latency, token usage —
is appended to a local log file. Nothing is overwritten.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(".incident-scribe")
LOG_FILE = LOG_DIR / "audit.jsonl"


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_api_call(
    stage: str,
    model: str,
    prompt_version: str,
    input_text: str,
    output_text: str,
    latency_ms: float,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Append an immutable audit entry for a Claude API call."""
    _ensure_log_dir()

    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "stage": stage,
        "model": model,
        "prompt_version": prompt_version,
        "input_hash": hashlib.sha256(input_text.encode()).hexdigest()[:16],
        "output_hash": hashlib.sha256(output_text.encode()).hexdigest()[:16],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": round(latency_ms, 1),
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


class ApiTimer:
    """Context manager to time API calls."""

    def __init__(self) -> None:
        self.start: float = 0
        self.elapsed_ms: float = 0

    def __enter__(self) -> "ApiTimer":
        self.start = time.monotonic()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed_ms = (time.monotonic() - self.start) * 1000
