"""Tests for audit sanitization policy."""

from __future__ import annotations

from backend.app.commands.audit import (
    dump_sanitized_json,
    sanitize_error_message,
    sanitize_mal_response,
    sanitize_request_payload,
)


def test_sanitize_error_removes_bearer_token() -> None:
    msg = "Authorization failed Bearer abc.def.ghi secret=supersecret"
    cleaned = sanitize_error_message(msg)
    assert cleaned is not None
    assert "abc.def.ghi" not in cleaned
    assert "supersecret" not in cleaned
    assert "***REDACTED***" in cleaned


def test_sanitize_error_truncates() -> None:
    cleaned = sanitize_error_message("x" * 1000, max_length=50)
    assert cleaned is not None
    assert len(cleaned) <= 50


def test_sanitize_mal_response_strips_secrets_and_unknown() -> None:
    payload = {
        "status": "completed",
        "score": 9,
        "access_token": "tok_abc",
        "authorization": "Bearer x",
        "mystery_field": "nope",
        "num_episodes_watched": 24,
    }
    cleaned = sanitize_mal_response(payload)
    assert cleaned["status"] == "completed"
    assert cleaned["score"] == 9
    assert cleaned["num_episodes_watched"] == 24
    assert "access_token" not in cleaned
    assert "authorization" not in cleaned
    assert "mystery_field" not in cleaned


def test_sanitize_request_payload() -> None:
    cleaned = sanitize_request_payload(
        {"status": "watching", "score": 8, "client_secret": "nope"}
    )
    assert cleaned is not None
    assert cleaned["score"] == 8
    assert "client_secret" not in cleaned


def test_dump_sanitized_json_stable() -> None:
    text = dump_sanitized_json({"status": "accepted", "score": 1})
    assert '"score":1' in text
    assert "token" not in text
