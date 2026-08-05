"""Contract tests for MalClient list pagination."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.config import Settings
from backend.app.mal.errors import MalUnexpectedResponseError
from backend.tests.contract.helpers import build_mal_client
from backend.tests.fixtures.mal_api_responses import (
    ANIME_LIST_PAGE_ONE,
    ANIME_LIST_PAGE_TWO,
    EMPTY_ANIME_LIST,
)


def test_one_page_results(oauth_settings: Settings) -> None:
    page = {
        "data": ANIME_LIST_PAGE_TWO["data"],
        "paging": {},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            entries = [item async for item in client.iter_anime_list()]
            assert len(entries) == 1
            assert entries[0].mal_id == 1
            assert entries[0].title == "Cowboy Bebop"
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_multiple_pages(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "offset=1" in str(request.url):
            return httpx.Response(200, json=ANIME_LIST_PAGE_TWO)
        return httpx.Response(200, json=ANIME_LIST_PAGE_ONE)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            entries = [item async for item in client.iter_anime_list()]
            assert [e.mal_id for e in entries] == [9253, 1]
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_empty_list(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=EMPTY_ANIME_LIST)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            entries = [item async for item in client.iter_anime_list()]
            assert entries == []
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_missing_next_page_url(oauth_settings: Settings) -> None:
    page = {
        "data": ANIME_LIST_PAGE_TWO["data"],
        # paging key absent entirely
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            entries = [item async for item in client.iter_anime_list()]
            assert len(entries) == 1
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_malformed_pagination_data(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "paging": "bad"})

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalUnexpectedResponseError):
                async for _ in client.iter_anime_list():
                    pass
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_malformed_list_item(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"node": {"title": "no-id"}}], "paging": {}},
        )

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            with pytest.raises(MalUnexpectedResponseError):
                async for _ in client.iter_anime_list():
                    pass
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_cancellation_during_pagination(oauth_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "offset=1" in str(request.url):
            return httpx.Response(200, json=ANIME_LIST_PAGE_TWO)
        return httpx.Response(200, json=ANIME_LIST_PAGE_ONE)

    client = build_mal_client(oauth_settings, handler)

    async def _run() -> None:
        try:
            agen = client.iter_anime_list()
            first = await agen.__anext__()
            assert first.mal_id == 9253
            await agen.aclose()
        finally:
            await client.aclose()

    asyncio.run(_run())
