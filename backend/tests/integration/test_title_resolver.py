"""Integration tests for the full title-resolution pipeline (mocked MAL)."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.db.repositories.title_aliases import TitleAliasRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.domain.enums import MediaType
from backend.app.mal.client import MalClient
from backend.app.resolver.aliases import AliasService
from backend.app.resolver.errors import (
    ResolverAuthenticationError,
    ResolverTemporaryError,
)
from backend.app.resolver.models import (
    AmbiguousOutcome,
    NotFoundOutcome,
    ResolvedOutcome,
    ResolveTitleRequest,
)
from backend.app.resolver.policy import ResolverPolicy
from backend.app.resolver.service import TitleResolver
from backend.app.services.clock import FixedClock
from backend.tests.contract.helpers import StaticTokenProvider, build_mal_client

HXH_1999 = {
    "id": 136,
    "title": "Hunter x Hunter",
    "alternative_titles": {"synonyms": [], "en": "Hunter x Hunter", "ja": None},
    "media_type": "tv",
    "start_date": "1999-10-16",
    "num_episodes": 62,
    "status": "finished_airing",
}

HXH_2011 = {
    "id": 11061,
    "title": "Hunter x Hunter (2011)",
    "alternative_titles": {
        "synonyms": ["Hunter x Hunter"],
        "en": "Hunter x Hunter",
        "ja": None,
    },
    "media_type": "tv",
    "start_date": "2011-10-02",
    "num_episodes": 148,
    "status": "finished_airing",
}

STEINS = {
    "id": 9253,
    "title": "Steins;Gate",
    "alternative_titles": {
        "synonyms": ["Steins Gate"],
        "en": "Steins;Gate",
        "ja": "シュタインズ・ゲート",
    },
    "media_type": "tv",
    "start_date": "2011-04-06",
    "num_episodes": 24,
    "status": "finished_airing",
}

PLUTO_ANIME = {
    "id": 53275,
    "title": "Pluto",
    "alternative_titles": {"synonyms": [], "en": "Pluto", "ja": None},
    "media_type": "ona",
    "start_date": "2023-10-26",
    "num_episodes": 8,
    "status": "finished_airing",
}

PLUTO_MANGA = {
    "id": 7675,
    "title": "Pluto",
    "alternative_titles": {"synonyms": [], "en": "Pluto", "ja": None},
    "media_type": "manga",
    "start_date": "2003-09-09",
    "num_chapters": 65,
    "num_volumes": 8,
    "status": "finished",
}

VINLAND_S2 = {
    "id": 49387,
    "title": "Vinland Saga Season 2",
    "alternative_titles": {
        "synonyms": ["Vinland Saga 2"],
        "en": "Vinland Saga Season 2",
        "ja": None,
    },
    "media_type": "tv",
    "start_date": "2023-01-10",
    "num_episodes": 24,
    "status": "finished_airing",
}

FMA_BH = {
    "id": 5114,
    "title": "Fullmetal Alchemist: Brotherhood",
    "alternative_titles": {
        "synonyms": ["FMA Brotherhood"],
        "en": "Fullmetal Alchemist: Brotherhood",
        "ja": None,
    },
    "media_type": "tv",
    "start_date": "2009-04-05",
    "num_episodes": 64,
    "status": "finished_airing",
}


class MalMockRouter:
    """Route mocked MAL GETs for resolver integration tests."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.anime_search: dict[str, list[dict[str, Any]]] = {}
        self.manga_search: dict[str, list[dict[str, Any]]] = {}
        self.anime_details: dict[int, dict[str, Any]] = {}
        self.manga_details: dict[int, dict[str, Any]] = {}
        self.fail_anime_search = False
        self.fail_manga_search = False
        self.auth_fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.auth_fail:
            return httpx.Response(401, json={"message": "unauthorized"})

        path = urlparse(str(request.url)).path
        qs = parse_qs(urlparse(str(request.url)).query)

        if path.endswith("/anime") and request.method == "GET":
            if self.fail_anime_search:
                return httpx.Response(503, json={"message": "down"})
            q = (qs.get("q") or [""])[0].casefold()
            nodes = self._lookup(self.anime_search, q)
            return httpx.Response(
                200, json={"data": [{"node": n} for n in nodes], "paging": {}}
            )

        if path.endswith("/manga") and request.method == "GET":
            if self.fail_manga_search:
                return httpx.Response(503, json={"message": "down"})
            q = (qs.get("q") or [""])[0].casefold()
            nodes = self._lookup(self.manga_search, q)
            return httpx.Response(
                200, json={"data": [{"node": n} for n in nodes], "paging": {}}
            )

        anime_detail = _match_id_path(path, "/anime/")
        if anime_detail is not None and request.method == "GET":
            payload = self.anime_details.get(anime_detail)
            if payload is None:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json=payload)

        manga_detail = _match_id_path(path, "/manga/")
        if manga_detail is not None and request.method == "GET":
            payload = self.manga_details.get(manga_detail)
            if payload is None:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json=payload)

        return httpx.Response(404, json={"message": f"unhandled {path}"})

    @staticmethod
    def _lookup(
        mapping: dict[str, list[dict[str, Any]]], query: str
    ) -> list[dict[str, Any]]:
        if query in mapping:
            return mapping[query]
        for key, value in mapping.items():
            if key in query or query in key:
                return value
        return []


def _match_id_path(path: str, prefix: str) -> int | None:
    if prefix not in path:
        return None
    tail = path.split(prefix, 1)[1]
    if "/" in tail or not tail.isdigit():
        return None
    return int(tail)


def _build_resolver(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    router: MalMockRouter,
    *,
    policy: ResolverPolicy | None = None,
) -> tuple[TitleResolver, MalClient]:
    client = build_mal_client(oauth_settings, router.handler)
    alias_service = AliasService(
        repository=TitleAliasRepository(db_session),
        clock=fixed_clock,
    )
    resolver = TitleResolver(
        mal_client=client,
        alias_service=alias_service,
        policy=policy or ResolverPolicy(),
    )
    return resolver, client


@pytest.fixture
def user_id(db_session: Session) -> str:
    return UserRepository(db_session).get_or_create_local_user().id


def test_anime_only_clear_resolve(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.anime_search["steins;gate"] = [STEINS]
    router.anime_details[9253] = dict(STEINS)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> ResolvedOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(
                    title="Steins;Gate", media_type=MediaType.ANIME
                ),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, ResolvedOutcome)
        return outcome

    outcome = asyncio.run(_run())
    assert outcome.media.mal_id == 9253
    assert outcome.media.media_type is MediaType.ANIME
    assert not any("/manga" in str(c.url) for c in router.calls)


def test_manga_only_resolve(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.manga_search["pluto"] = [PLUTO_MANGA]
    router.manga_details[7675] = dict(PLUTO_MANGA)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> ResolvedOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(title="Pluto", media_type=MediaType.MANGA),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, ResolvedOutcome)
        return outcome

    outcome = asyncio.run(_run())
    assert outcome.media.mal_id == 7675
    assert outcome.media.media_type is MediaType.MANGA


def test_unspecified_media_type_searches_both(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.anime_search["pluto"] = [PLUTO_ANIME]
    router.manga_search["pluto"] = [PLUTO_MANGA]
    router.anime_details[53275] = dict(PLUTO_ANIME)
    router.manga_details[7675] = dict(PLUTO_MANGA)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> AmbiguousOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(title="Pluto"),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, AmbiguousOutcome)
        return outcome

    outcome = asyncio.run(_run())
    types = {c.media.media_type for c in outcome.candidates}
    assert MediaType.ANIME in types
    assert MediaType.MANGA in types
    assert len(outcome.candidates) <= 3


def test_remake_year_disambiguation(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.anime_search["hunter x hunter"] = [HXH_1999, HXH_2011]
    router.anime_details[136] = dict(HXH_1999)
    router.anime_details[11061] = dict(HXH_2011)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> ResolvedOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(
                    title="Hunter x Hunter 2011",
                    media_type=MediaType.ANIME,
                ),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, ResolvedOutcome)
        return outcome

    outcome = asyncio.run(_run())
    assert outcome.media.mal_id == 11061


def test_remake_ambiguity_without_year(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.anime_search["hunter x hunter"] = [HXH_1999, HXH_2011]
    router.anime_details[136] = dict(HXH_1999)
    router.anime_details[11061] = dict(HXH_2011)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> AmbiguousOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(
                    title="Hunter x Hunter",
                    media_type=MediaType.ANIME,
                ),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, AmbiguousOutcome)
        return outcome

    outcome = asyncio.run(_run())
    ids = {c.media.mal_id for c in outcome.candidates}
    assert 136 in ids
    assert 11061 in ids


def test_season_disambiguation(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.anime_search["vinland saga"] = [VINLAND_S2]
    router.anime_details[49387] = dict(VINLAND_S2)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> ResolvedOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(
                    title="Vinland Saga season 2",
                    media_type=MediaType.ANIME,
                ),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, ResolvedOutcome)
        return outcome

    outcome = asyncio.run(_run())
    assert outcome.media.mal_id == 49387


def test_not_found(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> NotFoundOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(
                    title="zzzznotitlexyz", media_type=MediaType.ANIME
                ),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, NotFoundOutcome)
        return outcome

    asyncio.run(_run())


def test_alias_assisted_resolution(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.anime_search["fma"] = [STEINS]
    router.anime_details[5114] = dict(FMA_BH)
    router.anime_details[9253] = dict(STEINS)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> ResolvedOutcome:
        await resolver.save_alias(
            user_id=user_id,
            alias="FMA",
            media_type=MediaType.ANIME,
            mal_id=5114,
            canonical_title="Fullmetal Alchemist: Brotherhood",
        )
        db_session.commit()
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(title="FMA", media_type=MediaType.ANIME),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, ResolvedOutcome)
        return outcome

    outcome = asyncio.run(_run())
    assert outcome.media.mal_id == 5114


def test_partial_search_failure_continues(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.fail_anime_search = True
    router.manga_search["pluto"] = [PLUTO_MANGA]
    router.manga_details[7675] = dict(PLUTO_MANGA)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> ResolvedOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(title="Pluto"),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, ResolvedOutcome)
        return outcome

    outcome = asyncio.run(_run())
    assert outcome.media.mal_id == 7675


def test_all_searches_fail_raises_temporary(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.fail_anime_search = True
    router.fail_manga_search = True
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> None:
        try:
            with pytest.raises(ResolverTemporaryError):
                await resolver.resolve(
                    user_id=user_id,
                    request=ResolveTitleRequest(title="Pluto"),
                )
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_auth_failure_raises(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.auth_fail = True
    transport = httpx.MockTransport(router.handler)
    http_client = httpx.AsyncClient(transport=transport, timeout=5.0)
    client = MalClient(
        settings=oauth_settings,
        token_provider=StaticTokenProvider(),
        http_client=http_client,
    )
    resolver = TitleResolver(
        mal_client=client,
        alias_service=AliasService(
            repository=TitleAliasRepository(db_session),
            clock=fixed_clock,
        ),
    )

    async def _run() -> None:
        try:
            with pytest.raises(ResolverAuthenticationError):
                await resolver.resolve(
                    user_id=user_id,
                    request=ResolveTitleRequest(
                        title="Steins;Gate", media_type=MediaType.ANIME
                    ),
                )
        finally:
            await client.aclose()

    asyncio.run(_run())


def test_request_count_bounds(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    nodes = [
        {**STEINS, "id": 9000 + i, "title": f"Steins;Gate Variant {i}"}
        for i in range(8)
    ]
    router.anime_search["steins;gate"] = nodes
    for node in nodes:
        router.anime_details[node["id"]] = dict(node)

    policy = ResolverPolicy(max_enrich_candidates=3, max_mal_gets=10, search_limit=10)
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router, policy=policy
    )

    async def _run() -> None:
        try:
            await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(
                    title="Steins;Gate", media_type=MediaType.ANIME
                ),
            )
        finally:
            await client.aclose()

    asyncio.run(_run())
    assert len(router.calls) <= policy.max_mal_gets


def test_existing_list_flag_from_enrichment(
    oauth_settings: Settings,
    db_session: Session,
    fixed_clock: FixedClock,
    user_id: str,
) -> None:
    router = MalMockRouter()
    router.anime_search["steins;gate"] = [STEINS]
    router.anime_details[9253] = {
        **STEINS,
        "my_list_status": {
            "status": "completed",
            "score": 9,
            "num_episodes_watched": 24,
            "is_rewatching": False,
            "updated_at": "2024-01-15T12:00:00+00:00",
        },
    }
    resolver, client = _build_resolver(
        oauth_settings, db_session, fixed_clock, router
    )

    async def _run() -> ResolvedOutcome:
        try:
            outcome = await resolver.resolve(
                user_id=user_id,
                request=ResolveTitleRequest(
                    title="Steins;Gate", media_type=MediaType.ANIME
                ),
            )
        finally:
            await client.aclose()
        assert isinstance(outcome, ResolvedOutcome)
        return outcome

    asyncio.run(_run())
    assert any("/anime/9253" in str(c.url) for c in router.calls)
