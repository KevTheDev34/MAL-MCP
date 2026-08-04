"""Unit tests for log redaction of OAuth secrets."""

from __future__ import annotations

import logging

from backend.app.auth.errors import OAuthTokenExchangeError
from backend.app.logging_config import RedactingFilter
from backend.tests.fixtures.mal_oauth_responses import (
    FIXTURE_ACCESS_TOKEN,
    FIXTURE_REFRESH_TOKEN,
)


def test_redacting_filter_masks_token_key_values() -> None:
    filt = RedactingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            f"access_token={FIXTURE_ACCESS_TOKEN} "
            f"refresh_token={FIXTURE_REFRESH_TOKEN}"
        ),
        args=(),
        exc_info=None,
    )
    assert filt.filter(record)
    assert FIXTURE_ACCESS_TOKEN not in record.getMessage()
    assert FIXTURE_REFRESH_TOKEN not in record.getMessage()
    assert "***REDACTED***" in record.getMessage()


def test_redacting_filter_masks_bearer_header() -> None:
    filt = RedactingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f"Authorization: Bearer {FIXTURE_ACCESS_TOKEN}",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record)
    message = record.getMessage()
    assert FIXTURE_ACCESS_TOKEN not in message
    assert "***REDACTED***" in message


def test_redacting_filter_masks_code_verifier() -> None:
    filt = RedactingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="code_verifier=abc123verifiershouldberedacted000000000000",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record)
    assert "abc123verifiershouldberedacted000000000000" not in record.getMessage()


def test_auth_error_message_has_no_tokens() -> None:
    exc = OAuthTokenExchangeError("MAL token endpoint returned an error")
    assert FIXTURE_ACCESS_TOKEN not in str(exc)
    assert FIXTURE_REFRESH_TOKEN not in str(exc)
