"""Shared helpers for MalClient contract tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from backend.app.auth.mal_oauth import MalOAuthHttpClient
from backend.app.auth.service import MalOAuthService
from backend.app.config import Settings
from backend.app.mal.client import MalClient
from backend.app.services.clock import FixedClock
from backend.app.services.encryption import EncryptionService
from backend.tests.fixtures.mal_oauth_responses import (
    FIXTURE_ACCESS_TOKEN,
    FIXTURE_REFRESH_TOKEN,
)


class StaticTokenProvider:
    """Test double that returns a fixed access token."""

    def __init__(self, token: str = FIXTURE_ACCESS_TOKEN) -> None:
        self.token = token
        self.force_refresh_calls = 0
        self.calls = 0

    async def get_valid_access_token(self, *, force_refresh: bool = False) -> str:
        self.calls += 1
        if force_refresh:
            self.force_refresh_calls += 1
        return self.token


def build_mal_client(
    settings: Settings,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    token_provider: Any | None = None,
) -> MalClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, timeout=5.0)
    provider = token_provider or StaticTokenProvider()
    return MalClient(
        settings=settings,
        token_provider=provider,
        http_client=http_client,
    )


def seed_oauth_tokens(
    service: MalOAuthService,
    *,
    expires_in: timedelta,
    access_token: str = FIXTURE_ACCESS_TOKEN,
    refresh_token: str = FIXTURE_REFRESH_TOKEN,
) -> None:
    user = service._users.get_or_create_local_user()
    service._token_store.save_tokens(
        user_id=user.id,
        provider_user_id="123456",
        provider_username="fixture_mal_user",
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=service._clock.now() + expires_in,
    )
    service._session.commit()


def build_oauth_service(
    db_session: Session,
    oauth_settings: Settings,
    fixed_clock: FixedClock,
    encryption_service: EncryptionService,
    handler: Callable[[httpx.Request], httpx.Response],
) -> MalOAuthService:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    return MalOAuthService(
        session=db_session,
        settings=oauth_settings,
        encryption=encryption_service,
        clock=fixed_clock,
        http_client=MalOAuthHttpClient(oauth_settings, http_client),
    )
