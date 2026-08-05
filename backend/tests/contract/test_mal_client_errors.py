"""Contract tests for MalClient error mapping and retries."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.config import Settings
from backend.app.mal.errors import (
    MalAuthenticationError,
    MalAuthorizationError,
    MalNotFoundError,
    MalRateLimitError,
    MalTemporaryError,
    MalUnexpectedResponseError,
    MalValidationError,
)
from backend.tests.contract.helpers import build_mal_client
from backend.tests.fixtures.mal_api_responses import MAL_USER


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("backend.app.mal.client.asyncio.sleep", _no_sleep)


def test_400_validation(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "bad"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalValidationError):
                await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_401_authentication(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "unauthorized"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalAuthenticationError):
                await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_403_authorization(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalAuthorizationError):
                await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_404_not_found(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "missing"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalNotFoundError):
                await client.get_anime(1)
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_429_rate_limit_then_success(
    oauth_settings: Settings,
    no_sleep: None,
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                json={"message": "slow down"},
                headers={"Retry-After": "1"},
            )
        return httpx.Response(200, json=MAL_USER)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            user = await client.get_current_user()
            assert user.id == 123456
        finally:
            await client.aclose()

    asyncio.run(_run())
    assert calls["n"] == 2


def test_429_exhausted(oauth_settings: Settings, no_sleep: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "2"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalRateLimitError) as exc_info:
                await client.get_current_user()
            assert exc_info.value.retry_after == 2.0
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_503_retried_for_get(oauth_settings: Settings, no_sleep: None) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=MAL_USER)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())
    assert calls["n"] == 3


def test_timeout(oauth_settings: Settings, no_sleep: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalTemporaryError, match="timed out"):
                await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_connection_failure(oauth_settings: Settings, no_sleep: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalTemporaryError, match="connection"):
                await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_malformed_json(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not-json",
            headers={"Content-Type": "text/plain"},
        )

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalUnexpectedResponseError):
                await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_missing_required_fields(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "missing-id"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalUnexpectedResponseError):
                await client.get_current_user()
        finally:
            await client.aclose()

    asyncio.run(_run())
