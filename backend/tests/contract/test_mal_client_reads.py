"""Contract tests for MalClient read operations."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.config import Settings
from backend.app.mal.errors import MalNotFoundError
from backend.tests.contract.helpers import build_mal_client
from backend.tests.fixtures.mal_api_responses import (
    ANIME_DETAILS_WITH_LIST_STATUS,
    ANIME_DETAILS_WITHOUT_LIST_STATUS,
    ANIME_NODE,
    ANIME_SEARCH_RESPONSE,
    EMPTY_SEARCH_RESPONSE,
    MAL_USER,
    MANGA_DETAILS_WITH_LIST_STATUS,
    MANGA_DETAILS_WITHOUT_LIST_STATUS,
    MANGA_NODE,
    MANGA_SEARCH_RESPONSE,
)


def test_current_user_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/users/@me")
        return httpx.Response(200, json=MAL_USER)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            user = await client.get_current_user()
            assert user.id == 123456
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_anime_search_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "anime" in request.url.path
        assert request.url.params["q"] == "Steins"
        return httpx.Response(200, json=ANIME_SEARCH_RESPONSE)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            results = await client.search_anime("Steins", limit=5)
            assert len(results) == 1
            assert results[0].id == 9253
            assert results[0].english_title == "Steins;Gate"
            assert results[0].release_year == 2011
            assert results[0].num_episodes == 24
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_manga_search_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MANGA_SEARCH_RESPONSE)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            results = await client.search_manga("Monster")
            assert results[0].id == 642
            assert results[0].num_chapters == 162
            assert results[0].num_volumes == 18
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_empty_search_results(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=EMPTY_SEARCH_RESPONSE)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            assert await client.search_anime("zzzz-no-match") == []
            assert await client.search_manga("zzzz-no-match") == []
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_anime_details_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/anime/9253")
        return httpx.Response(200, json=ANIME_NODE)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            details = await client.get_anime(9253)
            assert details.title == "Steins;Gate"
            assert details.media_type == "tv"
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_manga_details_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=MANGA_NODE)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            details = await client.get_manga(642)
            assert details.title == "Monster"
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_missing_media(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalNotFoundError):
                await client.get_anime(999999)
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_existing_list_entry(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/anime/9253")
        assert "my_list_status" in request.url.params["fields"]
        return httpx.Response(200, json=ANIME_DETAILS_WITH_LIST_STATUS)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            entry = await client.get_anime_list_entry(9253)
            assert entry is not None
            assert entry.mal_id == 9253
            assert entry.title == "Steins;Gate"
            assert entry.list_status.score == 9
            assert entry.list_status.num_episodes_watched == 24
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_entry_not_on_list(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/manga/" in request.url.path:
            return httpx.Response(200, json=MANGA_DETAILS_WITHOUT_LIST_STATUS)
        return httpx.Response(200, json=ANIME_DETAILS_WITHOUT_LIST_STATUS)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            assert await client.get_anime_list_entry(9253) is None
            assert await client.get_manga_list_entry(642) is None
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_manga_list_entry_success(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/manga/642")
        assert "my_list_status" in request.url.params["fields"]
        return httpx.Response(200, json=MANGA_DETAILS_WITH_LIST_STATUS)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            entry = await client.get_manga_list_entry(642)
            assert entry is not None
            assert entry.title == "Monster"
            assert entry.list_status.num_chapters_read == 162
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_list_entry_missing_media(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalNotFoundError):
                await client.get_anime_list_entry(999999)
        finally:
            await client.aclose()

    asyncio.run(_run())
