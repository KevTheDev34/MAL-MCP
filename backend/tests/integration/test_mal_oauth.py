"""Integration tests for MAL OAuth endpoints with mocked MAL HTTP."""

from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import UTC, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.mal_oauth import MalOAuthHttpClient
from backend.app.auth.service import MalOAuthService
from backend.app.config import Settings, get_settings
from backend.app.db.models import OAuthCredential, OAuthState
from backend.app.dependencies import get_clock, get_db_session, get_mal_oauth_service
from backend.app.main import create_app
from backend.app.services.clock import FixedClock
from backend.app.services.encryption import EncryptionService
from backend.tests.fixtures.mal_oauth_responses import (
    FIXTURE_ACCESS_TOKEN,
    FIXTURE_REFRESH_TOKEN,
    MAL_USER_RESPONSE,
    TOKEN_RESPONSE,
)


def _make_client(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    transport: httpx.MockTransport,
) -> TestClient:
    get_settings.cache_clear()
    application = create_app()
    http_client = httpx.AsyncClient(
        transport=transport,
        timeout=oauth_settings.request_timeout_seconds,
    )
    encryption = EncryptionService(oauth_settings.token_encryption_key)

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    async def override_oauth_service() -> Any:
        # Reuse the shared AsyncClient for the TestClient lifetime; do not close
        # it per-request or subsequent requests will fail.
        service = MalOAuthService(
            session=db_session,
            settings=oauth_settings,
            encryption=encryption,
            clock=fixed_clock,
            http_client=MalOAuthHttpClient(oauth_settings, http_client),
        )
        yield service

    application.dependency_overrides[get_db_session] = override_get_db
    application.dependency_overrides[get_settings] = lambda: oauth_settings
    application.dependency_overrides[get_clock] = lambda: fixed_clock
    application.dependency_overrides[get_mal_oauth_service] = override_oauth_service

    client = TestClient(application)
    client._mal_http_client = http_client  # type: ignore[attr-defined]
    return client


def test_start_redirects_and_persists_state(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    client = _make_client(
        db_session,
        oauth_settings,
        fixed_clock,
        httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    response = client.get("/auth/mal/start", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "myanimelist.net"
    assert parsed.path == "/v1/oauth2/authorize"
    params = parse_qs(parsed.query)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["test-client-id"]
    assert params["code_challenge_method"] == ["plain"]
    assert "state" in params
    assert "code_challenge" in params

    states = db_session.scalars(select(OAuthState)).all()
    assert len(states) == 1
    assert states[0].state == params["state"][0]
    assert states[0].code_verifier == params["code_challenge"][0]


def test_start_without_config_returns_503(
    db_session: Session,
    fixed_clock: FixedClock,
) -> None:
    settings = Settings(
        mal_client_id="",
        mal_client_secret="",
        token_encryption_key="",
        mal_redirect_uri="http://testserver/auth/mal/callback",
    )
    client = _make_client(
        db_session,
        settings,
        fixed_clock,
        httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    response = client.get("/auth/mal/start", follow_redirects=False)
    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "oauth_configuration_error"
    assert "access_token" not in body["message"].lower()


def test_callback_happy_path(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json=TOKEN_RESPONSE)
        if "/users/@me" in str(request.url):
            return httpx.Response(200, json=MAL_USER_RESPONSE)
        return httpx.Response(404)

    client = _make_client(
        db_session, oauth_settings, fixed_clock, httpx.MockTransport(handler)
    )
    start = client.get("/auth/mal/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]

    with caplog.at_level(logging.INFO):
        response = client.get(
            "/auth/mal/callback",
            params={"code": "auth-code", "state": state},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True
    assert payload["mal_user_id"] == "123456"
    assert payload["mal_username"] == "fixture_mal_user"
    assert "access_token" not in payload
    assert "refresh_token" not in payload

    credential = db_session.scalar(select(OAuthCredential))
    assert credential is not None
    assert credential.encrypted_access_token != FIXTURE_ACCESS_TOKEN
    assert credential.encrypted_refresh_token != FIXTURE_REFRESH_TOKEN

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert FIXTURE_ACCESS_TOKEN not in log_text
    assert FIXTURE_REFRESH_TOKEN not in log_text

    status = client.get("/auth/mal/status")
    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert status.json()["mal_username"] == "fixture_mal_user"


def test_callback_invalid_state(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    client = _make_client(
        db_session,
        oauth_settings,
        fixed_clock,
        httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    response = client.get(
        "/auth/mal/callback",
        params={"code": "auth-code", "state": "unknown"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "oauth_state_invalid"
    assert db_session.scalar(select(OAuthCredential)) is None


def test_callback_expired_state(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    client = _make_client(
        db_session,
        oauth_settings,
        fixed_clock,
        httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    start = client.get("/auth/mal/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    row = db_session.scalar(select(OAuthState).where(OAuthState.state == state))
    assert row is not None
    row.expires_at = fixed_clock.now() - timedelta(minutes=1)
    db_session.commit()

    response = client.get(
        "/auth/mal/callback",
        params={"code": "auth-code", "state": state},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "oauth_state_expired"


def test_callback_reused_state(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json=TOKEN_RESPONSE)
        if "/users/@me" in str(request.url):
            return httpx.Response(200, json=MAL_USER_RESPONSE)
        return httpx.Response(404)

    client = _make_client(
        db_session, oauth_settings, fixed_clock, httpx.MockTransport(handler)
    )
    start = client.get("/auth/mal/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    first = client.get("/auth/mal/callback", params={"code": "c1", "state": state})
    assert first.status_code == 200

    second = client.get("/auth/mal/callback", params={"code": "c2", "state": state})
    assert second.status_code == 400
    assert second.json()["error"] == "oauth_state_invalid"


def test_callback_provider_error(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    client = _make_client(
        db_session,
        oauth_settings,
        fixed_clock,
        httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    response = client.get(
        "/auth/mal/callback",
        params={"error": "access_denied", "error_description": "nope"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "oauth_provider_denied"


def test_callback_token_exchange_failure_consumes_state(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = _make_client(
        db_session, oauth_settings, fixed_clock, httpx.MockTransport(handler)
    )
    start = client.get("/auth/mal/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    response = client.get(
        "/auth/mal/callback",
        params={"code": "bad", "state": state},
    )
    assert response.status_code == 502
    assert response.json()["error"] == "oauth_token_exchange_error"

    row = db_session.scalar(select(OAuthState).where(OAuthState.state == state))
    assert row is not None
    assert row.consumed_at is not None

    retry = client.get("/auth/mal/callback", params={"code": "bad", "state": state})
    assert retry.status_code == 400


def test_status_when_disconnected(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    client = _make_client(
        db_session,
        oauth_settings,
        fixed_clock,
        httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    response = client.get("/auth/mal/status")
    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "provider": "mal",
        "mal_user_id": None,
        "mal_username": None,
        "token_expires_at": None,
        "reconnect_required": False,
    }


def test_disconnect_is_idempotent(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json=TOKEN_RESPONSE)
        if "/users/@me" in str(request.url):
            return httpx.Response(200, json=MAL_USER_RESPONSE)
        return httpx.Response(404)

    client = _make_client(
        db_session, oauth_settings, fixed_clock, httpx.MockTransport(handler)
    )
    start = client.get("/auth/mal/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(
        "/auth/mal/callback",
        params={"code": "c", "state": state},
    )
    assert callback.status_code == 200

    first = client.post("/auth/mal/disconnect")
    assert first.status_code == 200
    assert first.json()["connected"] is False
    assert db_session.scalar(select(OAuthCredential)) is None

    second = client.post("/auth/mal/disconnect")
    assert second.status_code == 200
    assert second.json()["connected"] is False


def test_token_refresh_via_status_helper_path(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
) -> None:
    """Exercise get_valid_access_token refresh through the service after connect."""
    from backend.tests.fixtures.mal_oauth_responses import REFRESHED_TOKEN_RESPONSE

    responses: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            body = request.content.decode()
            if "grant_type=refresh_token" in body:
                responses.append("refresh")
                return httpx.Response(200, json=REFRESHED_TOKEN_RESPONSE)
            responses.append("exchange")
            return httpx.Response(200, json=TOKEN_RESPONSE)
        if "/users/@me" in str(request.url):
            return httpx.Response(200, json=MAL_USER_RESPONSE)
        return httpx.Response(404)

    client = _make_client(
        db_session, oauth_settings, fixed_clock, httpx.MockTransport(handler)
    )
    start = client.get("/auth/mal/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(
        "/auth/mal/callback",
        params={"code": "c", "state": state},
    )
    assert callback.status_code == 200

    credential = db_session.scalar(select(OAuthCredential))
    assert credential is not None
    old_cipher = credential.encrypted_access_token
    credential.expires_at = fixed_clock.now() + timedelta(seconds=30)
    db_session.commit()

    # Call get_valid_access_token via a fresh service using the same mock transport
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )
    service = MalOAuthService(
        session=db_session,
        settings=oauth_settings,
        encryption=EncryptionService(oauth_settings.token_encryption_key),
        clock=fixed_clock,
        http_client=MalOAuthHttpClient(oauth_settings, http_client),
    )

    import asyncio

    async def _run() -> str:
        try:
            return await service.get_valid_access_token()
        finally:
            await service.aclose()

    token = asyncio.run(_run())
    assert "refresh" in responses
    assert token != FIXTURE_ACCESS_TOKEN
    refreshed = db_session.scalar(select(OAuthCredential))
    assert refreshed is not None
    assert refreshed.encrypted_access_token != old_cipher
    assert refreshed.last_refresh_at is not None
    assert refreshed.last_refresh_at.replace(tzinfo=UTC) == fixed_clock.now()
