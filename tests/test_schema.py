"""Tests for pydantic schema validation."""

from incident_scribe.schema import IncidentEvent, IncidentReport, TimelineEntry


def test_incident_event_valid():
    event = IncidentEvent(
        message_id="msg-123",
        event_type="alert_fired",
        description="PagerDuty alert for high error rate",
    )
    assert event.message_id == "msg-123"
    assert event.event_type == "alert_fired"


def test_timeline_entry():
    entry = TimelineEntry(time="2024-04-18 14:21:00 UTC", event="Alert fired")
    assert "14:21" in entry.time


def test_incident_report_minimal():
    report = IncidentReport(
        summary="Test incident",
        impact="No users affected",
        timeline=[TimelineEntry(time="14:00", event="Test event")],
        root_cause="Under investigation",
        remediation="None needed",
    )
    assert report.summary == "Test incident"
    assert report.open_questions == []
    assert report.lessons_learned == []


def test_incident_report_full():
    report = IncidentReport(
        summary="DB connection pool exhaustion",
        impact="3200 users got 503s",
        timeline=[
            TimelineEntry(time="14:21", event="Job started"),
            TimelineEntry(time="14:29", event="Resolved"),
        ],
        root_cause="Missing index on events.tenant_id",
        remediation="Killed job, adding index",
        open_questions=["Why didn't slow query alert fire?"],
        lessons_learned=["Isolate scheduled jobs from primary"],
    )
    assert len(report.timeline) == 2
    assert len(report.open_questions) == 1
