"""Drive the real Anthropic SDK against a mock transport.

These tests exist because the old suite mocked the client away entirely, so a
call the installed SDK rejects (``temperature=`` is a TypeError since anthropic
1.x) shipped green. Here the SDK serializes a genuine request and parses a
genuine response; only the network is fake.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import anthropic
import httpx2
import pytest

from incident_scribe import claude
from incident_scribe.schema import ExtractedEvents, Message, MessageStream
from incident_scribe.scribe import generate_report_from_stream


def _message(payload: dict, stop_reason: str = "end_turn", model: str = "claude-sonnet-5-5"):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 40},
    }


class FakeAPI:
    """Records every request; answers count_tokens and messages from queues."""

    def __init__(self, replies: list[dict], input_tokens: int = 500) -> None:
        self.replies = list(replies)
        self.input_tokens = input_tokens
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": self.input_tokens})
        return httpx2.Response(200, json=self.replies.pop(0))

    def client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self.handler)),
        )

    def message_bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/messages")]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # audit log writes under .incident-scribe/
    for var in ("INCIDENT_SCRIBE_MODEL", "INCIDENT_SCRIBE_EFFORT", "INCIDENT_SCRIBE_MAX_TOKENS"):
        monkeypatch.delenv(var, raising=False)


def _stream() -> MessageStream:
    t0 = datetime(2026, 4, 18, 14, 21, tzinfo=timezone.utc)
    return MessageStream(
        source_type="slack_export",
        messages=[
            Message(id="msg-1", actor="pagerduty", timestamp=t0, text="FIRING: 5xx > 5%"),
            Message(
                id="msg-2",
                actor="alice",
                timestamp=t0.replace(minute=40),
                text="rolled back; key AKIAABCDEFGHIJKLMNOP leaked in logs",
            ),
        ],
    )


def test_request_shape_is_accepted_by_installed_sdk():
    api = FakeAPI([_message({"events": []})])
    result = claude.call_structured(
        api.client(),
        system="sys",
        user_content="thread",
        output_model=ExtractedEvents,
        stage="extract",
    )
    assert result.events == []

    (body,) = api.message_bodies()
    assert body["model"] == "claude-sonnet-5-5"
    for removed in ("temperature", "top_p", "top_k"):
        assert removed not in body
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    msg_request = next(r for r in api.requests if r.url.path.endswith("/messages"))
    assert "server-side-fallback-2026-07-01" in msg_request.headers["anthropic-beta"]


def test_fallbacks_not_sent_to_models_that_reject_them(monkeypatch):
    monkeypatch.setenv("INCIDENT_SCRIBE_MODEL", "claude-haiku-5-5")
    api = FakeAPI([_message({"events": []}, model="claude-haiku-5-5")])
    claude.call_structured(
        api.client(), system="s", user_content="u", output_model=ExtractedEvents, stage="x"
    )
    (body,) = api.message_bodies()
    assert "fallbacks" not in body


def test_over_budget_prompt_fails_closed_without_a_paid_call():
    api = FakeAPI([], input_tokens=250_000)
    with pytest.raises(claude.TokenBudgetExceeded):
        claude.call_structured(
            api.client(),
            system="s",
            user_content="u",
            output_model=ExtractedEvents,
            stage="extract",
            max_input_tokens=100_000,
        )
    assert api.message_bodies() == []


def test_refusal_is_raised_not_parsed():
    reply = _message({"events": []}, stop_reason="refusal")
    reply["content"] = []
    api = FakeAPI([reply])
    with pytest.raises(claude.ClaudeCallError, match="declined"):
        claude.call_structured(
            api.client(), system="s", user_content="u", output_model=ExtractedEvents, stage="x"
        )


def test_truncated_output_is_reported():
    reply = _message({"events": []}, stop_reason="max_tokens")
    reply["content"] = [{"type": "text", "text": '{"events": ['}]
    api = FakeAPI([reply])
    with pytest.raises(claude.ClaudeCallError, match="max_tokens"):
        claude.call_structured(
            api.client(), system="s", user_content="u", output_model=ExtractedEvents, stage="x"
        )


def test_end_to_end_resolves_times_and_redacts():
    api = FakeAPI(
        [
            _message(
                {
                    "events": [
                        {"message_id": "msg-1", "event_type": "alert_fired", "description": "5xx"},
                        {"message_id": "msg-9", "event_type": "other", "description": "ghost"},
                    ]
                }
            ),
            # corrective retry after the unknown ID
            _message(
                {
                    "events": [
                        {"message_id": "msg-1", "event_type": "alert_fired", "description": "5xx"},
                        {"message_id": "msg-2", "event_type": "rollback", "description": "rb"},
                    ]
                }
            ),
            _message(
                {
                    "summary": "s",
                    "impact": "i",
                    "timeline": [
                        {"message_id": "msg-2", "event": "Rolled back"},
                        {"message_id": "msg-1", "event": "Alert fired"},
                        {"message_id": "msg-404", "event": "Invented"},
                    ],
                    "root_cause": "rc",
                    "remediation": "r",
                    "open_questions": [],
                    "lessons_learned": [],
                }
            ),
        ]
    )
    report = generate_report_from_stream(_stream(), client=api.client())

    assert [e.event for e in report.timeline] == ["Alert fired", "Rolled back"]
    assert report.timeline[0].time == "2026-04-18 14:21:00 UTC"
    assert report.timeline[1].time == "2026-04-18 14:40:00 UTC"

    bodies = api.message_bodies()
    assert len(bodies) == 3
    assert "msg-9" in bodies[1]["messages"][0]["content"]  # retry names the bad ID
    sent = json.dumps(bodies)
    assert "AKIAABCDEFGHIJKLMNOP" not in sent
    assert "[AWS_ACCESS_KEY_1]" in sent
