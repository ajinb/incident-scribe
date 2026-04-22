"""Pydantic models for structured incident report output."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    source_type: str = Field(description="'slack_export' or 'plain_text'")


class IncidentEvent(BaseModel):
    """A discrete event extracted from the thread by the LLM."""

    message_id: str = Field(description="ID of the source message")
    event_type: str = Field(
        description="alert_fired, acknowledged, deploy, rollback, resolved, etc."
    )
    description: str = Field(description="One-line description of the event")


class TimelineEntry(BaseModel):
    """A timeline entry with a deterministic timestamp resolved from message IDs."""

    time: str = Field(description="UTC timestamp string")
    event: str = Field(description="Description of what happened")


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
    lessons_learned: list[str] = Field(
        default_factory=list, description="Key takeaways"
    )
