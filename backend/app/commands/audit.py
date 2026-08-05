"""Centralized audit sanitization for persisted command data."""

from __future__ import annotations

import json
import re
from typing import Any, Final

_REDACTED: Final[str] = "***REDACTED***"
_DEFAULT_MAX_ERROR_LENGTH: Final[int] = 500
_DEFAULT_MAX_ORIGINAL_TEXT: Final[int] = 4096

_SENSITIVE_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(token|secret|password|api[_-]?key|authorization|credential|code_verifier|"
    r"cookie|csrf)",
    re.IGNORECASE,
)
_KEY_VALUE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b([\w-]*(?:token|secret|password|api[_-]?key|authorization|"
    r"credential|code_verifier|cookie|csrf)[\w-]*)\s*([:=])\s*([^\s,;]+)"
)
_BEARER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(Bearer)\s+([A-Za-z0-9\-._~+/]+=*)"
)
_QUERY_SECRET_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|code|client_secret|api_key)=)([^&]*)"
)

_ALLOWED_MAL_RESPONSE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "status",
        "score",
        "num_episodes_watched",
        "num_watched_episodes",
        "num_chapters_read",
        "num_volumes_read",
        "is_rewatching",
        "is_rereading",
        "updated_at",
        "start_date",
        "finish_date",
        "priority",
        "num_times_rewatched",
        "num_times_reread",
        "rewatch_value",
        "reread_value",
        "tags",
        "comments",
    }
)


def redact_text(text: str) -> str:
    """Remove credential-shaped substrings from free text."""
    redacted = _BEARER_PATTERN.sub(rf"\1 {_REDACTED}", text)
    redacted = _KEY_VALUE_PATTERN.sub(rf"\1\2{_REDACTED}", redacted)
    return _QUERY_SECRET_PATTERN.sub(rf"\1{_REDACTED}", redacted)


def sanitize_error_message(
    message: str | None,
    *,
    max_length: int = _DEFAULT_MAX_ERROR_LENGTH,
) -> str | None:
    """Truncate and redact an error message for audit storage."""
    if message is None:
        return None
    cleaned = redact_text(message).strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3] + "..."
    return cleaned


def sanitize_original_text(
    text: str | None,
    *,
    max_length: int = _DEFAULT_MAX_ORIGINAL_TEXT,
) -> str | None:
    """Bound user-provided original text without inventing content."""
    if text is None:
        return None
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def sanitize_mal_response(payload: Any) -> dict[str, Any]:
    """Keep only allowlisted MAL list-status fields."""
    if payload is None:
        return {"status": "accepted"}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {"summary": sanitize_error_message(payload) or "unparseable"}
    if not isinstance(payload, dict):
        return {"summary": "non_object_response"}
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if _SENSITIVE_KEY_PATTERN.search(str(key)):
            continue
        if key not in _ALLOWED_MAL_RESPONSE_FIELDS and key != "status":
            continue
        if isinstance(value, str):
            cleaned[key] = redact_text(value)
        else:
            cleaned[key] = value
    if not cleaned:
        return {"status": "accepted"}
    return cleaned


def sanitize_request_payload(payload: Any) -> dict[str, Any] | None:
    """Sanitize a MAL update request body for persistence."""
    if payload is None:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {"summary": sanitize_error_message(payload) or "unparseable"}
    if not isinstance(payload, dict):
        return {"summary": "non_object_request"}
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if _SENSITIVE_KEY_PATTERN.search(str(key)):
            continue
        if isinstance(value, str):
            cleaned[key] = redact_text(value)
        else:
            cleaned[key] = value
    return cleaned


def dump_sanitized_json(payload: Any) -> str:
    """Serialize a sanitized payload to compact JSON."""
    if isinstance(payload, dict):
        data = payload
    else:
        data = sanitize_mal_response(payload)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
