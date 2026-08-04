"""Sanitized MAL OAuth HTTP fixtures for tests."""

from __future__ import annotations

FIXTURE_ACCESS_TOKEN = "test-access-token-value-do-not-log"
FIXTURE_REFRESH_TOKEN = "test-refresh-token-value-do-not-log"
FIXTURE_ACCESS_TOKEN_REFRESHED = "test-access-token-refreshed-value"
FIXTURE_REFRESH_TOKEN_REFRESHED = "test-refresh-token-refreshed-value"

TOKEN_RESPONSE = {
    "token_type": "Bearer",
    "expires_in": 3600,
    "access_token": FIXTURE_ACCESS_TOKEN,
    "refresh_token": FIXTURE_REFRESH_TOKEN,
}

REFRESHED_TOKEN_RESPONSE = {
    "token_type": "Bearer",
    "expires_in": 3600,
    "access_token": FIXTURE_ACCESS_TOKEN_REFRESHED,
    "refresh_token": FIXTURE_REFRESH_TOKEN_REFRESHED,
}

MAL_USER_RESPONSE = {
    "id": 123456,
    "name": "fixture_mal_user",
}
