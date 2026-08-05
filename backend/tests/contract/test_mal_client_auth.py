"""Contract tests for MalClient authentication integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.mal.client import MalClient
from backend.app.mal.errors import MalAuthenticationError, MalTemporaryError
from backend.app.services.clock import FixedClock
from backend.app.services.encryption import EncryptionService
from backend.tests.contract.helpers import (
    StaticTokenProvider,
    build_mal_client,
    build_oauth_service,
    seed_oauth_tokens,
)
from backend.tests.fixtures.mal_api_responses import MAL_USER
from backend.tests.fixtures.mal_oauth_responses import (
    FIXTURE_ACCESS_TOKEN,
    FIXTURE_ACCESS_TOKEN_REFRESHED,
    REFRESHED_TOKEN_RESPONSE,
)


def test_valid_access_token_on_current_user(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {FIXTURE_ACCESS_TOKEN}"
        return httpx.Response(200, json=MAL_USER)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            user = await client.get_current_user()
            assert user.id == 123456
            assert user.name == "fixture_mal_user"
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_expired_token_proactive_refresh_then_success(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/token" in url:
            calls.append("refresh")
            return httpx.Response(200, json=REFRESHED_TOKEN_RESPONSE)
        calls.append("api")
        assert (
            request.headers["Authorization"]
            == f"Bearer {FIXTURE_ACCESS_TOKEN_REFRESHED}"
        )
        return httpx.Response(200, json=MAL_USER)

    oauth = build_oauth_service(
        db_session, oauth_settings, fixed_clock, encryption_service, handler
    )
    seed_oauth_tokens(oauth, expires_in=timedelta(seconds=30))
    client = MalClient(
        settings=oauth_settings,
        token_provider=oauth,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        ),
    )

    async def _run() -> None:
        try:
            user = await client.get_current_user()
            assert user.id == 123456
        finally:
            await client.aclose()
            await oauth.aclose()

    asyncio.run(_run())
    assert calls == ["refresh", "api"]


def test_refresh_failure_definitive_requires_auth_error(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_token"})

    oauth = build_oauth_service(
        db_session, oauth_settings, fixed_clock, encryption_service, handler
    )
    seed_oauth_tokens(oauth, expires_in=timedelta(seconds=30))
    client = MalClient(settings=oauth_settings, token_provider=oauth)

    async def _run() -> None:
        try:
            with pytest.raises(MalAuthenticationError):
                await client.get_current_user()
        finally:
            await client.aclose()
            await oauth.aclose()

    asyncio.run(_run())
    credential = oauth._token_store.get_credential(
        oauth._users.get_or_create_local_user().id
    )
    assert credential is not None
    assert credential.encrypted_access_token is None


def test_api_401_force_refresh_and_retry_success(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
) -> None:
    api_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/token" in url:
            return httpx.Response(200, json=REFRESHED_TOKEN_RESPONSE)
        api_calls["n"] += 1
        auth = request.headers.get("Authorization", "")
        if api_calls["n"] == 1:
            assert FIXTURE_ACCESS_TOKEN in auth
            return httpx.Response(401, json={"error": "invalid_token"})
        assert FIXTURE_ACCESS_TOKEN_REFRESHED in auth
        return httpx.Response(200, json=MAL_USER)

    oauth = build_oauth_service(
        db_session, oauth_settings, fixed_clock, encryption_service, handler
    )
    seed_oauth_tokens(oauth, expires_in=timedelta(hours=1))
    client = MalClient(
        settings=oauth_settings,
        token_provider=oauth,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        ),
    )

    async def _run() -> None:
        try:
            user = await client.get_current_user()
            assert user.name == "fixture_mal_user"
        finally:
            await client.aclose()
            await oauth.aclose()

    asyncio.run(_run())
    assert api_calls["n"] == 2


def test_api_401_after_retry_fails(oauth_settings: Settings) -> None:
    provider = StaticTokenProvider()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "still_bad"})

    client = build_mal_client(oauth_settings, handler, token_provider=provider)

    async def _run() -> None:
        try:
            with pytest.raises(MalAuthenticationError):
                await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())
    assert provider.force_refresh_calls == 1


def test_no_credential_record(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    oauth = build_oauth_service(
        db_session, oauth_settings, fixed_clock, encryption_service, handler
    )
    client = MalClient(settings=oauth_settings, token_provider=oauth)

    async def _run() -> None:
        try:
            with pytest.raises(MalAuthenticationError, match="not connected"):
                await client.get_current_user()
        finally:
            await client.aclose()
            await oauth.aclose()

    asyncio.run(_run())


def test_transient_refresh_does_not_clear_tokens(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    oauth = build_oauth_service(
        db_session, oauth_settings, fixed_clock, encryption_service, handler
    )
    seed_oauth_tokens(oauth, expires_in=timedelta(seconds=30))
    client = MalClient(settings=oauth_settings, token_provider=oauth)

    async def _run() -> None:
        try:
            with pytest.raises(MalTemporaryError):
                await client.get_current_user()
        finally:
            await client.aclose()
            await oauth.aclose()

    asyncio.run(_run())
    credential = oauth._token_store.get_credential(
        oauth._users.get_or_create_local_user().id
    )
    assert credential is not None
    assert credential.encrypted_access_token is not None
