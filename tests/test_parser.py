"""Tests for the parser module."""

import json
from pathlib import Path

from incident_scribe.parser import parse_plain_text, parse_slack_export, parse_thread  # noqa: I001

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_parse_slack_export_list():
    data = json.dumps(
        [
            {"user": "alice", "ts": "1713451260.000100", "text": "Alert fired"},
            {"user": "bob", "ts": "1713451320.000200", "text": "Acking"},
        ]
    )
    stream = parse_slack_export(data)
    assert stream.source_type == "slack_export"
    assert len(stream.messages) == 2
    assert stream.messages[0].actor == "alice"
    assert stream.messages[1].actor == "bob"
    assert stream.messages[0].id == "msg-1713451260.000100"


def test_parse_slack_export_dict():
    data = json.dumps(
        {
            "messages": [
                {"user": "alice", "ts": "1713451260.000100", "text": "Alert"},
            ]
        }
    )
    stream = parse_slack_export(data)
    assert len(stream.messages) == 1


def test_parse_plain_text_bracket_format():
    text = (
        "[14:21] pagerduty-bot: FIRING: High error rate\n"
        "[14:22] oncall-eng: Acking. Looking at it.\n"
    )
    stream = parse_plain_text(text)
    assert stream.source_type == "plain_text"
    assert len(stream.messages) == 2
    assert stream.messages[0].actor == "pagerduty-bot"
    assert "FIRING" in stream.messages[0].text


def test_parse_thread_auto_detect_json():
    data = json.dumps(
        [
            {"user": "test", "ts": "1713451260.000100", "text": "hello"},
        ]
    )
    stream = parse_thread(data)
    assert stream.source_type == "slack_export"


def test_parse_thread_auto_detect_text():
    text = "[14:21] bot: alert fired\n[14:22] eng: looking\n"
    stream = parse_thread(text)
    assert stream.source_type == "plain_text"


def test_messages_sorted_by_timestamp():
    data = json.dumps(
        [
            {"user": "b", "ts": "1713451320.000200", "text": "second"},
            {"user": "a", "ts": "1713451260.000100", "text": "first"},
        ]
    )
    stream = parse_slack_export(data)
    assert stream.messages[0].actor == "a"
    assert stream.messages[1].actor == "b"


def test_parse_sample_thread_json():
    sample = FIXTURES_DIR / "sample_thread.json"
    if not sample.exists():
        return  # skip if fixture not copied
    stream = parse_thread(sample.read_text())
    assert len(stream.messages) > 0
