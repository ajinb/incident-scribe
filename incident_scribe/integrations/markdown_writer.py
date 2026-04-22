"""Render an IncidentReport as clean markdown."""

from __future__ import annotations

from ..schema import IncidentReport


def render_markdown(report: IncidentReport) -> str:
    """Convert an IncidentReport to formatted markdown."""
    lines = ["# Incident Report", ""]

    lines.extend(["## Summary", report.summary, ""])

    lines.extend(["## Impact", report.impact, ""])

    lines.append("## Timeline")
    for entry in report.timeline:
        lines.append(f"- **{entry.time}** — {entry.event}")
    lines.append("")

    lines.extend(["## Root Cause", report.root_cause, ""])

    lines.extend(["## Remediation", report.remediation, ""])

    if report.open_questions:
        lines.append("## Open Questions")
        for q in report.open_questions:
            lines.append(f"- {q}")
        lines.append("")

    if report.lessons_learned:
        lines.append("## Lessons Learned")
        for lesson in report.lessons_learned:
            lines.append(f"- {lesson}")
        lines.append("")

    return "\n".join(lines)
