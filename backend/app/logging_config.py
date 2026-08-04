"""Structured logging with secret redaction."""

from __future__ import annotations

import logging
import re
from typing import Final

_SENSITIVE_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(token|secret|password|api[_-]?key|authorization|credential|code_verifier)",
    re.IGNORECASE,
)

_REDACTED: Final[str] = "***REDACTED***"

_KEY_VALUE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b([\w-]*(?:token|secret|password|api[_-]?key|authorization|"
    r"credential|code_verifier)[\w-]*)\s*([:=])\s*([^\s,;]+)"
)

_BEARER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(Bearer)\s+([A-Za-z0-9\-._~+/]+=*)"
)


class RedactingFilter(logging.Filter):
    """Redact credential-like key/value pairs from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_text(record.msg)

        if isinstance(record.args, dict):
            record.args = {
                key: _redact_value(key, value) for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(
                _redact_text(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def _redact_value(key: str, value: object) -> object:
    if _SENSITIVE_KEY_PATTERN.search(key):
        return _REDACTED
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    # Bearer headers first so key=value redaction does not leave the token behind.
    redacted = _BEARER_PATTERN.sub(rf"\1 {_REDACTED}", text)
    return _KEY_VALUE_PATTERN.sub(rf"\1\2{_REDACTED}", redacted)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once with structured-ish formatting and redaction."""
    root = logging.getLogger()
    if getattr(root, "_mal_assistant_configured", False):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(RedactingFilter())

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root._mal_assistant_configured = True  # type: ignore[attr-defined]
