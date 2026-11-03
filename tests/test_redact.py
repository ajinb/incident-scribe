"""Redaction must catch the things people actually paste into incident channels."""

import pytest

from incident_scribe.redact import Redactor, redact

SECRETS = [
    ("AWS_ACCESS_KEY", "creds AKIAIOSFODNN7EXAMPLE in env"),
    ("GITHUB_TOKEN", "token ghp_" + "a" * 36),
    ("SLACK_TOKEN", "xoxb-1234567890-abcdefghij"),
    ("ANTHROPIC_KEY", "sk-ant-api03-" + "x" * 40),
    ("JWT", "Authorization: eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4fw"),
    ("URL_CREDENTIALS", "postgres://admin:hunter2@db.internal:5432/app"),
    ("SECRET_VALUE", "password=CorrectHorse99"),
    ("PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"),
]


@pytest.mark.parametrize(("kind", "text"), SECRETS)
def test_secrets_are_redacted_by_default(kind, text):
    out = redact(text)
    assert f"[{kind}_1]" in out


def test_pii_only_in_all_mode():
    text = "customer jane@example.com from 10.0.4.17 called +1 303 555 0142"
    assert redact(text, "secrets") == text
    out = redact(text, "all")
    assert "jane@example.com" not in out and "[EMAIL_1]" in out
    assert "[IPV4_1]" in out
    assert "[PHONE_1]" in out


def test_card_numbers_need_a_valid_luhn_checksum():
    assert "[CARD_1]" in redact("card 4111 1111 1111 1111", "all")
    assert "1234 5678 9012 3456" in redact("order 1234 5678 9012 3456", "all")


def test_placeholders_are_stable_across_messages():
    r = Redactor(mode="all")
    a = r.redact("ping ops@example.com")
    b = r.redact("ops@example.com and dev@example.com")
    assert a == "ping [EMAIL_1]"
    assert b == "[EMAIL_1] and [EMAIL_2]"
    assert r.findings == {"EMAIL": 2}


def test_off_mode_is_a_noop():
    assert redact("AKIAIOSFODNN7EXAMPLE", "off") == "AKIAIOSFODNN7EXAMPLE"
