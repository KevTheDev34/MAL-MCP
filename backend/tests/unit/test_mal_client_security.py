"""Security tests for MalClient logging and update allowlists."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.logging_config import configure_logging
from backend.app.mal.errors import MalAuthenticationError
from backend.app.mal.models import AnimeListUpdate, MangaListUpdate
from backend.tests.contract.helpers import StaticTokenProvider, build_mal_client
from backend.tests.fixtures.mal_oauth_responses import FIXTURE_ACCESS_TOKEN


def test_tokens_absent_from_logs(
    oauth_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_logging("DEBUG")
    secret = "super-secret-access-token-xyz"
    provider = StaticTokenProvider(token=secret)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    client = build_mal_client(oauth_settings, handler, token_provider=provider)

    async def _run() -> None:
        try:
            with pytest.raises(MalAuthenticationError) as exc_info:
                await client.get_current_user()
            message = exc_info.value.message
            assert secret not in message
            assert "Authorization" not in message
            assert FIXTURE_ACCESS_TOKEN not in message or secret != FIXTURE_ACCESS_TOKEN
        finally:
            await client.aclose()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(_run())

    combined = " ".join(record.getMessage() for record in caplog.records)
    assert secret not in combined
    assert "Bearer " not in combined or "***" in combined or "Bearer" not in combined


def test_authorization_header_absent_from_errors(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "nope"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(Exception) as exc_info:
                await client.get_current_user()
            text = str(exc_info.value)
            assert "Bearer" not in text
            assert FIXTURE_ACCESS_TOKEN not in text
            assert "Authorization" not in text
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_sensitive_response_bodies_not_in_errors(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": "bad", "hint": "token=leaked-secret-value"},
        )

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(Exception) as exc_info:
                await client.get_current_user()
            assert "leaked-secret-value" not in str(exc_info.value)
            assert "leaked-secret-value" not in exc_info.value.message  # type: ignore[attr-defined]
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_update_payload_rejects_unsupported_fields() -> None:
    with pytest.raises(ValidationError):
        AnimeListUpdate.model_validate(
            {"score": 5, "tags": "should-not-be-allowed"}
        )
    with pytest.raises(ValidationError):
        MangaListUpdate.model_validate(
            {"score": 5, "comments": "nope"}
        )
