"""Local redaction of secrets and PII before any text leaves the machine.

Incident channels are where people paste the thing they should not paste: a
leaked key, a connection string, a customer's email. Everything sent to the
model passes through :func:`redact` first, and the audit log only ever sees the
redacted text.

Placeholders are stable within one run — the same value always becomes the same
token (``[EMAIL_1]``) — so the model can still tell that two messages mention
the same address without ever seeing it.

Modes:
    ``off``      no redaction (explicit opt-out)
    ``secrets``  credentials, tokens, keys, connection strings (default)
    ``all``      secrets plus emails, IP addresses, phone and card numbers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

RedactMode = Literal["off", "secrets", "all"]

# Order matters: the most specific patterns run first so a JWT is not half
# eaten by the generic bearer rule.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "PRIVATE_KEY",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OPENAI_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("AWS_ACCESS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})")),
    ("SLACK_TOKEN", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("SLACK_WEBHOOK", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+")),
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("STRIPE_KEY", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("URL_CREDENTIALS", re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")),
    ("BEARER_TOKEN", re.compile(r"(?i)(?<=bearer )[A-Za-z0-9._~+/=-]{16,}")),
    (
        "SECRET_VALUE",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)"
            r"[\"']?\s*[:=]\s*[\"']?(?P<v>[^\s\"',;]{6,})"
        ),
    ),
]

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    (
        "IPV4",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
    ),
    ("IPV6", re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){4,7}[0-9a-fA-F]{1,4}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("PHONE", re.compile(r"(?<!\w)\+?\d{1,3}[ .-]?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b")),
]


def _luhn_ok(candidate: str) -> bool:
    digits = [int(c) for c in candidate if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class Redactor:
    """Stateful redactor: one instance per run keeps placeholders consistent."""

    mode: RedactMode = "secrets"
    _seen: dict[tuple[str, str], str] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)

    @property
    def findings(self) -> dict[str, int]:
        """How many distinct values were redacted, per category."""
        return dict(self._counts)

    def _placeholder(self, kind: str, value: str) -> str:
        key = (kind, value)
        if key not in self._seen:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            self._seen[key] = f"[{kind}_{self._counts[kind]}]"
        return self._seen[key]

    def redact(self, text: str) -> str:
        if self.mode == "off" or not text:
            return text
        patterns = list(_SECRET_PATTERNS)
        if self.mode == "all":
            patterns += _PII_PATTERNS
        for kind, pattern in patterns:

            def _sub(m: re.Match[str], kind: str = kind) -> str:
                # A pattern with a ``v`` group keeps its context (``password=``)
                # and replaces only the value.
                whole = m.group(0)
                value = m.groupdict().get("v") or whole
                if kind == "CARD" and not _luhn_ok(value):
                    return whole
                start = m.start("v") - m.start() if "v" in m.groupdict() else 0
                return whole[:start] + self._placeholder(kind, value) + whole[start + len(value) :]

            text = pattern.sub(_sub, text)
        return text


def redact(text: str, mode: RedactMode = "secrets") -> str:
    """One-shot convenience wrapper. Use :class:`Redactor` across a whole thread."""
    return Redactor(mode=mode).redact(text)
