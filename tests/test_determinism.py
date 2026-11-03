"""Parsing is deterministic: same input → same IDs and timestamps, no wall clock."""

from datetime import datetime, timezone

from incident_scribe.integrations.slack_api import SlackAPIError, fetch_thread
from incident_scribe.parser import parse_plain_text, parse_slack_export, parse_thread
from incident_scribe.schema import IncidentEvent, Message, MessageStream
from incident_scribe.scribe import validate_events

THREAD = "[23:58] pagerduty: FIRING api 5xx\n[00:03] alice: ack, looking\n[00:20] alice: resolved"


def test_plain_text_ids_are_sequential_and_stable():
    a = parse_plain_text(THREAD, reference_date="2026-04-18")
    b = parse_plain_text(THREAD, reference_date="2026-04-18")
    assert [m.id for m in a.messages] == ["msg-0001", "msg-0002", "msg-0003"]
    assert a == b


def test_midnight_rollover():
    s = parse_plain_text(THREAD, reference_date="2026-04-18")
    assert s.messages[0].timestamp == datetime(2026, 4, 18, 23, 58, tzinfo=timezone.utc)
    assert s.messages[1].timestamp == datetime(2026, 4, 19, 0, 3, tzinfo=timezone.utc)


def test_timezone_is_applied_then_stored_as_utc():
    s = parse_plain_text("[2026-04-18 09:00] bob: deploy", tz="America/Denver")
    assert s.messages[0].timestamp == datetime(2026, 4, 18, 15, 0, tzinfo=timezone.utc)


def test_dated_line_sets_reference_for_undated_lines():
    s = parse_thread("[2026-01-02 10:00] a: one\n[10:05] b: two")
    assert s.messages[1].timestamp == datetime(2026, 1, 2, 10, 5, tzinfo=timezone.utc)


def test_no_wall_clock_without_reference_date():
    s = parse_plain_text("[10:00] a: one")
    assert s.messages[0].timestamp.year == 1970  # reproducible, visibly "date unknown"


def test_bad_slack_ts_inherits_previous_time():
    s = parse_slack_export('[{"ts": "1713451260.0001", "text": "a"}, {"ts": "oops", "text": "b"}]')
    assert s.messages[0].timestamp == s.messages[1].timestamp


def test_validate_events_drops_unknown_and_duplicates_in_thread_order():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stream = MessageStream(
        source_type="plain_text",
        messages=[Message(id=f"msg-{i}", actor="x", timestamp=t, text="") for i in (1, 2)],
    )
    events = [
        IncidentEvent(message_id="msg-2", event_type="resolved", description="r"),
        IncidentEvent(message_id="msg-1", event_type="alert_fired", description="a"),
        IncidentEvent(message_id="msg-1", event_type="alert_fired", description="dup"),
        IncidentEvent(message_id="msg-7", event_type="other", description="ghost"),
    ]
    valid, unknown = validate_events(stream, events)
    assert [e.message_id for e in valid] == ["msg-1", "msg-2"]
    assert unknown == ["msg-7"]


def test_slack_api_paginates_and_resolves_names():
    pages = {
        "": {
            "ok": True,
            "messages": [{"ts": "1.0", "user": "U1", "text": "fire"}],
            "response_metadata": {"next_cursor": "c2"},
        },
        "c2": {"ok": True, "messages": [{"ts": "2.0", "user": "U1", "text": "fixed"}]},
    }

    def fake(method, params, token):
        assert token == "xoxb-test"
        if method == "users.info":
            return {"ok": True, "user": {"name": "alice", "profile": {"display_name": "Alice"}}}
        return pages[params.get("cursor", "")]

    stream = fetch_thread("C1", "1.0", token="xoxb-test", fetch=fake)
    assert stream.source_type == "slack_api"
    assert [m.text for m in stream.messages] == ["fire", "fixed"]
    assert {m.actor for m in stream.messages} == {"Alice"}


def test_slack_api_error_surfaces():
    def fake(method, params, token):
        return {"ok": False, "error": "channel_not_found"}

    try:
        fetch_thread("C1", "1.0", token="xoxb-test", fetch=fake)
    except SlackAPIError as e:
        assert "channel_not_found" in str(e)
    else:
        raise AssertionError("expected SlackAPIError")
