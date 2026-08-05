"""Bounded MAL search helpers for title resolution."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.enums import MediaType
from backend.app.domain.media import ResolvedMedia
from backend.app.mal.client import MalClient
from backend.app.mal.domain_mapping import (
    anime_details_to_resolved_media,
    manga_details_to_resolved_media,
)
from backend.app.mal.errors import (
    MalAuthenticationError,
    MalError,
    MalNotFoundError,
    MalRateLimitError,
    MalTemporaryError,
)
from backend.app.mal.models import AnimeSearchResult, MangaSearchResult
from backend.app.resolver.errors import (
    ResolverAuthenticationError,
    ResolverTemporaryError,
)
from backend.app.resolver.normalize import (
    expand_abbreviation,
    normalize_for_search,
)
from backend.app.resolver.policy import ResolverPolicy


@dataclass(frozen=True)
class SearchHit:
    """Deduped search hit before enrichment scoring."""

    media_type: MediaType
    mal_id: int
    media: ResolvedMedia
    source: str = "search"


def build_search_queries(
    *,
    original_title: str,
    remaining_title: str,
    max_variants: int,
) -> list[str]:
    """Build a bounded, deduplicated list of MAL search strings."""
    queries: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        value = normalize_for_search(raw)
        if not value:
            return
        key = value.casefold()
        if key in seen:
            return
        seen.add(key)
        queries.append(value)

    _add(original_title)
    if remaining_title.strip() and remaining_title.strip() != original_title.strip():
        _add(remaining_title)
    expanded = expand_abbreviation(original_title) or expand_abbreviation(
        remaining_title
    )
    if expanded:
        _add(expanded)

    return queries[:max_variants]


async def search_mal_candidates(
    client: MalClient,
    *,
    queries: list[str],
    media_types: list[MediaType],
    policy: ResolverPolicy,
    request_counter: list[int],
) -> list[SearchHit]:
    """Search MAL for candidate hits within request budgets."""
    hits: list[SearchHit] = []
    seen: set[tuple[MediaType, int]] = set()
    search_failures = 0
    searches_attempted = 0

    for media_type in media_types:
        for query in queries:
            if request_counter[0] >= policy.max_mal_gets:
                break
            searches_attempted += 1
            request_counter[0] += 1
            try:
                if media_type is MediaType.ANIME:
                    anime_results = await client.search_anime(
                        query, limit=policy.search_limit
                    )
                    for anime_item in anime_results:
                        _append_anime_hit(hits, seen, anime_item)
                else:
                    manga_results = await client.search_manga(
                        query, limit=policy.search_limit
                    )
                    for manga_item in manga_results:
                        _append_manga_hit(hits, seen, manga_item)
            except MalAuthenticationError as exc:
                raise ResolverAuthenticationError(exc.message) from exc
            except (MalTemporaryError, MalRateLimitError):
                search_failures += 1
                continue
            except MalError:
                search_failures += 1
                continue

    if searches_attempted > 0 and search_failures == searches_attempted:
        raise ResolverTemporaryError("All MAL title searches failed")

    return hits


def dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    """Preserve first-seen order by ``(media_type, mal_id)``."""
    seen: set[tuple[MediaType, int]] = set()
    out: list[SearchHit] = []
    for hit in hits:
        key = (hit.media_type, hit.mal_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def _append_anime_hit(
    hits: list[SearchHit],
    seen: set[tuple[MediaType, int]],
    item: AnimeSearchResult,
) -> None:
    key = (MediaType.ANIME, item.id)
    if key in seen:
        return
    seen.add(key)
    media = anime_details_to_resolved_media(
        item,
        confidence=0.0,
        confidence_reasons=[],
    )
    hits.append(
        SearchHit(media_type=MediaType.ANIME, mal_id=item.id, media=media)
    )


def _append_manga_hit(
    hits: list[SearchHit],
    seen: set[tuple[MediaType, int]],
    item: MangaSearchResult,
) -> None:
    key = (MediaType.MANGA, item.id)
    if key in seen:
        return
    seen.add(key)
    media = manga_details_to_resolved_media(
        item,
        confidence=0.0,
        confidence_reasons=[],
    )
    hits.append(
        SearchHit(media_type=MediaType.MANGA, mal_id=item.id, media=media)
    )


async def enrich_hit(
    client: MalClient,
    hit: SearchHit,
    *,
    request_counter: list[int],
    policy: ResolverPolicy,
) -> tuple[ResolvedMedia, bool] | None:
    """Refresh details and list membership for one candidate."""
    if request_counter[0] >= policy.max_mal_gets:
        return hit.media, False
    request_counter[0] += 1
    try:
        if hit.media_type is MediaType.ANIME:
            anime_details, on_list = await client.get_anime_resolution_context(
                hit.mal_id
            )
            media = anime_details_to_resolved_media(
                anime_details,
                confidence=0.0,
                confidence_reasons=[],
            )
            return media, on_list
        manga_details, on_list = await client.get_manga_resolution_context(hit.mal_id)
        media = manga_details_to_resolved_media(
            manga_details,
            confidence=0.0,
            confidence_reasons=[],
        )
        return media, on_list
    except MalNotFoundError:
        return None
    except MalAuthenticationError as exc:
        raise ResolverAuthenticationError(exc.message) from exc
    except (MalTemporaryError, MalRateLimitError, MalError):
        # Soft failure: keep search-row media without list bonus.
        return hit.media, False
