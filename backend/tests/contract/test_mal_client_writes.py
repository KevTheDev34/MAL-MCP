"""Contract tests for MalClient write operations."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.mal.errors import MalTemporaryError, MalValidationError
from backend.app.mal.models import AnimeListUpdate, MangaListUpdate
from backend.tests.contract.helpers import build_mal_client
from backend.tests.fixtures.mal_api_responses import (
    ANIME_LIST_STATUS,
    MANGA_LIST_STATUS,
)


def test_anime_update_success(oauth_settings: Settings) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path.endswith("/anime/9253/my_list_status")
        assert (
            request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        )
        body = parse_qs(request.content.decode())
        captured.update({k: v[0] for k, v in body.items()})
        return httpx.Response(
            200,
            json={
                **ANIME_LIST_STATUS,
                "score": 8,
                "num_episodes_watched": 12,
            },
        )

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            entry = await client.update_anime_list_entry(
                9253,
                AnimeListUpdate(score=8, num_watched_episodes=12),
            )
            assert entry.list_status.score == 8
            assert entry.list_status.num_episodes_watched == 12
        finally:
            await client.aclose()

    asyncio.run(_run())
    assert captured["score"] == "8"
    assert captured["num_watched_episodes"] == "12"
    assert "num_episodes_watched" not in captured


def test_manga_update_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = parse_qs(request.content.decode())
        assert body["num_chapters_read"] == ["65"]
        return httpx.Response(
            200,
            json={**MANGA_LIST_STATUS, "num_chapters_read": 65},
        )

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            entry = await client.update_manga_list_entry(
                642,
                MangaListUpdate(num_chapters_read=65),
            )
            assert entry.list_status.num_chapters_read == 65
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_anime_delete_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(200, json={})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            await client.delete_anime_list_entry(9253)
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_manga_delete_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(200, json={})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            await client.delete_manga_list_entry(642)
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_delete_missing_entry_is_noop(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            await client.delete_anime_list_entry(1)
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_invalid_update_payload_rejected_locally() -> None:
    with pytest.raises(ValidationError):
        AnimeListUpdate.model_validate({"score": 8, "unsupported": True})
    with pytest.raises(ValidationError):
        AnimeListUpdate()
    with pytest.raises(ValidationError):
        MangaListUpdate.model_validate({"priority": 1})


def test_remote_validation_failure(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_score"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalValidationError):
                await client.update_anime_list_entry(9253, AnimeListUpdate(score=8))
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_patch_503_not_retried(
    oauth_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("backend.app.mal.client.asyncio.sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalTemporaryError):
                await client.update_anime_list_entry(9253, AnimeListUpdate(score=8))
        finally:
            await client.aclose()

    asyncio.run(_run())
    assert calls["n"] == 1
