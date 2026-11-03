"""Pydantic models for structured incident report output.

The models double as the structured-output contract sent to Claude
(``output_format=``), so the API guarantees schema-valid JSON and the
retry-on-parse-failure loop is no longer the first line of defence. Semantic
checks — does a cited message ID exist? — still happen in ``scribe.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "alert_fired",
    "acknowledged",
    "investigation",
    "hypothesis",
    "deploy",
    "rollback",
    "mitigation",
    "resolved",
    "escalation",
    "decision",
    "communication",
    "other",
]


class Message(BaseModel):
    """A single normalized message from a Slack thread."""

    id: str = Field(description="Unique message identifier")
    actor: str = Field(description="Who sent the message (name or bot)")
    timestamp: datetime = Field(description="UTC timestamp of the message")
    text: str = Field(description="Message text content")
    reactions: list[str] = Field(default_factory=list)
    thread_parent: str | None = Field(default=None, description="Parent message ID if threaded")


class MessageStream(BaseModel):
    """Ordered list of normalized messages from a Slack thread."""

    messages: list[Message]
    source_type: str = Field(description="'slack_export', 'slack_api', or 'plain_text'")

    def ids(self) -> set[str]:
        return {m.id for m in self.messages}


class IncidentEvent(BaseModel):
    """A discrete event extracted from the thread by the LLM."""

    message_id: str = Field(description="ID of the source message, copied verbatim")
    event_type: EventType = Field(description="Kind of state change this message records")
    description: str = Field(description="One-line description of the event")


class ExtractedEvents(BaseModel):
    """Structured-output envelope for the extract stage (a top-level object, not an array)."""

    events: list[IncidentEvent]


class TimelineEntry(BaseModel):
    """A timeline entry with a deterministic timestamp resolved from message IDs."""

    time: str = Field(description="UTC timestamp string")
    event: str = Field(description="Description of what happened")


class TimelineDraft(BaseModel):
    """What the model writes for a timeline row: a message ID, never a clock reading."""

    message_id: str = Field(description="ID of the message this row is anchored to")
    event: str = Field(description="Description of what happened")


class ReportDraft(BaseModel):
    """Structured-output contract for the synthesize stage.

    Identical to :class:`IncidentReport` except that timeline rows cite a
    ``message_id``. ``scribe.py`` resolves each ID to its parsed timestamp, so
    the model cannot invent or mistype a time.
    """

    summary: str = Field(description="2-3 sentence incident summary")
    impact: str = Field(description="What was affected, user/revenue impact if known")
    timeline: list[TimelineDraft] = Field(description="Ordered timeline of key events")
    root_cause: str = Field(description="Root cause or 'Under investigation'")
    remediation: str = Field(description="Steps taken and planned")
    open_questions: list[str] = Field(description="Unresolved questions from the thread")
    lessons_learned: list[str] = Field(description="Key takeaways")


class IncidentReport(BaseModel):
    """The final structured incident report."""

    summary: str = Field(description="2-3 sentence incident summary")
    impact: str = Field(description="What was affected, user/revenue impact if known")
    timeline: list[TimelineEntry] = Field(description="Ordered timeline of key events")
    root_cause: str = Field(description="Root cause or 'Under investigation'")
    remediation: str = Field(description="Steps taken and planned")
    open_questions: list[str] = Field(
        default_factory=list, description="Unresolved questions from the thread"
    )
    lessons_learned: list[str] = Field(default_factory=list, description="Key takeaways")
