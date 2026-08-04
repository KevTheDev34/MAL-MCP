"""Unit tests for OAuth token refresh behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.app.auth.errors import MalReconnectRequiredError
from backend.app.auth.mal_oauth import MalOAuthHttpClient
from backend.app.auth.service import MalOAuthService
from backend.app.config import Settings
from backend.app.services.clock import FixedClock
from backend.app.services.encryption import EncryptionService
from backend.tests.fixtures.mal_oauth_responses import (
    FIXTURE_ACCESS_TOKEN,
    FIXTURE_ACCESS_TOKEN_REFRESHED,
    FIXTURE_REFRESH_TOKEN,
    REFRESHED_TOKEN_RESPONSE,
    TOKEN_RESPONSE,
)


def _build_service(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
    handler: httpx.MockTransport,
) -> MalOAuthService:
    http_client = httpx.AsyncClient(transport=handler, timeout=5.0)
    return MalOAuthService(
        session=db_session,
        settings=oauth_settings,
        encryption=encryption_service,
        clock=fixed_clock,
        http_client=MalOAuthHttpClient(oauth_settings, http_client),
    )


def test_get_valid_access_token_skips_refresh_when_fresh(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
) -> None:
    calls = {"token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["token"] += 1
        return httpx.Response(500, json={"error": "unexpected"})

    service = _build_service(
        db_session,
        oauth_settings,
        fixed_clock,
        encryption_service,
        httpx.MockTransport(handler),
    )
    service._token_store.save_tokens(
        user_id=service._users.get_or_create_local_user().id,
        provider_user_id="1",
        provider_username="u",
        access_token=FIXTURE_ACCESS_TOKEN,
        refresh_token=FIXTURE_REFRESH_TOKEN,
        expires_at=fixed_clock.now() + timedelta(hours=1),
    )
    db_session.commit()

    async def _run() -> str:
        try:
            return await service.get_valid_access_token()
        finally:
            await service.aclose()

    token = asyncio.run(_run())
    assert token == FIXTURE_ACCESS_TOKEN
    assert calls["token"] == 0


def test_get_valid_access_token_refreshes_near_expiry(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "oauth2/token" in str(request.url)
        return httpx.Response(200, json=REFRESHED_TOKEN_RESPONSE)

    service = _build_service(
        db_session,
        oauth_settings,
        fixed_clock,
        encryption_service,
        httpx.MockTransport(handler),
    )
    user = service._users.get_or_create_local_user()
    service._token_store.save_tokens(
        user_id=user.id,
        provider_user_id="1",
        provider_username="u",
        access_token=FIXTURE_ACCESS_TOKEN,
        refresh_token=FIXTURE_REFRESH_TOKEN,
        expires_at=fixed_clock.now() + timedelta(seconds=30),
    )
    db_session.commit()
    before = service._token_store.get_credential(user.id)
    assert before is not None
    old_cipher = before.encrypted_access_token

    async def _run() -> str:
        try:
            return await service.get_valid_access_token()
        finally:
            await service.aclose()

    token = asyncio.run(_run())
    assert token == FIXTURE_ACCESS_TOKEN_REFRESHED
    after = service._token_store.get_credential(user.id)
    assert after is not None
    assert after.encrypted_access_token != old_cipher
    assert after.last_refresh_at is not None
    assert after.last_refresh_at.replace(tzinfo=UTC) == fixed_clock.now()


def test_refresh_failure_clears_tokens_and_requires_reconnect(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_token"})

    service = _build_service(
        db_session,
        oauth_settings,
        fixed_clock,
        encryption_service,
        httpx.MockTransport(handler),
    )
    user = service._users.get_or_create_local_user()
    service._token_store.save_tokens(
        user_id=user.id,
        provider_user_id="1",
        provider_username="u",
        access_token=TOKEN_RESPONSE["access_token"],
        refresh_token=TOKEN_RESPONSE["refresh_token"],
        expires_at=datetime(2026, 8, 4, 15, 0, 30, tzinfo=UTC),
    )
    db_session.commit()

    async def _run() -> None:
        try:
            await service.get_valid_access_token()
        finally:
            await service.aclose()

    with pytest.raises(MalReconnectRequiredError):
        asyncio.run(_run())

    credential = service._token_store.get_credential(user.id)
    assert credential is not None
    assert credential.encrypted_access_token is None
    assert credential.encrypted_refresh_token is None
