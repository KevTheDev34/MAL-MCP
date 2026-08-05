"""Convert MAL transport models into application-domain models.

Lives outside the pure ``domain`` package so domain code never imports MAL
transport types or the HTTP client.
"""

from __future__ import annotations

from backend.app.domain.enums import (
    AnimeStatus,
    DomainErrorCode,
    MangaStatus,
    MediaType,
)
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.state import CurrentListState
from backend.app.mal.models import (
    AlternativeTitles,
    AnimeDetails,
    AnimeListEntry,
    AnimeSearchResult,
    MangaDetails,
    MangaListEntry,
    MangaSearchResult,
)


def _mal_score_to_domain(score: int) -> int | None:
    """Map MAL score (0 = unscored) to domain score (None = unscored)."""
    if score <= 0:
        return None
    return score


def _flatten_alternative_titles(
    titles: AlternativeTitles | None,
    *,
    exclude: set[str],
) -> list[str]:
    if titles is None:
        return []
    collected: list[str] = []
    for value in (*titles.synonyms, titles.en, titles.ja):
        if value is None:
            continue
        stripped = value.strip()
        if stripped and stripped not in exclude and stripped not in collected:
            collected.append(stripped)
    return collected


def _parse_anime_status(raw: str) -> AnimeStatus:
    try:
        return AnimeStatus(raw)
    except ValueError as exc:
        raise DomainValidationError(
            f"Unrecognized anime list status from MAL: {raw!r}",
            code=DomainErrorCode.INVALID_STATUS,
            field="status",
        ) from exc


def _parse_manga_status(raw: str) -> MangaStatus:
    try:
        return MangaStatus(raw)
    except ValueError as exc:
        raise DomainValidationError(
            f"Unrecognized manga list status from MAL: {raw!r}",
            code=DomainErrorCode.INVALID_STATUS,
            field="status",
        ) from exc


def anime_details_to_resolved_media(
    details: AnimeDetails | AnimeSearchResult,
    *,
    confidence: float,
    confidence_reasons: list[str] | None = None,
) -> ResolvedMedia:
    """Map anime details/search transport data to ``ResolvedMedia``."""
    exclude = {details.title.strip()} if details.title.strip() else set()
    return ResolvedMedia(
        mal_id=details.id,
        media_type=MediaType.ANIME,
        canonical_title=details.title,
        english_title=details.english_title,
        japanese_title=details.japanese_title,
        alternative_titles=_flatten_alternative_titles(
            details.alternative_titles,
            exclude=exclude,
        ),
        media_format=details.media_type,
        release_year=details.release_year,
        total_episodes=details.num_episodes,
        total_chapters=None,
        total_volumes=None,
        confidence=confidence,
        confidence_reasons=list(confidence_reasons or []),
    )


def manga_details_to_resolved_media(
    details: MangaDetails | MangaSearchResult,
    *,
    confidence: float,
    confidence_reasons: list[str] | None = None,
) -> ResolvedMedia:
    """Map manga details/search transport data to ``ResolvedMedia``."""
    exclude = {details.title.strip()} if details.title.strip() else set()
    return ResolvedMedia(
        mal_id=details.id,
        media_type=MediaType.MANGA,
        canonical_title=details.title,
        english_title=details.english_title,
        japanese_title=details.japanese_title,
        alternative_titles=_flatten_alternative_titles(
            details.alternative_titles,
            exclude=exclude,
        ),
        media_format=details.media_type,
        release_year=details.release_year,
        total_episodes=None,
        total_chapters=details.num_chapters,
        total_volumes=details.num_volumes,
        confidence=confidence,
        confidence_reasons=list(confidence_reasons or []),
    )


def not_on_list_state(media_type: MediaType) -> CurrentListState:
    """Explicit domain state when media exists but is absent from the user list."""
    return CurrentListState(
        media_type=media_type,
        is_on_list=False,
    )


def anime_list_entry_to_current_state(entry: AnimeListEntry) -> CurrentListState:
    """Map an on-list anime transport entry to ``CurrentListState``."""
    status = entry.list_status
    return CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=_parse_anime_status(status.status),
        score=_mal_score_to_domain(status.score),
        episode_progress=status.num_episodes_watched,
        chapter_progress=None,
        volume_progress=None,
    )


def manga_list_entry_to_current_state(entry: MangaListEntry) -> CurrentListState:
    """Map an on-list manga transport entry to ``CurrentListState``."""
    status = entry.list_status
    return CurrentListState(
        media_type=MediaType.MANGA,
        is_on_list=True,
        status=_parse_manga_status(status.status),
        score=_mal_score_to_domain(status.score),
        episode_progress=None,
        chapter_progress=status.num_chapters_read,
        volume_progress=status.num_volumes_read,
    )


def list_entry_or_none_to_current_state(
    media_type: MediaType,
    entry: AnimeListEntry | MangaListEntry | None,
) -> CurrentListState:
    """Convert a list lookup result (entry or ``None``) to domain state."""
    if entry is None:
        return not_on_list_state(media_type)
    if media_type is MediaType.ANIME:
        if not isinstance(entry, AnimeListEntry):
            raise DomainValidationError(
                "Expected AnimeListEntry for anime media type",
                code=DomainErrorCode.MEDIA_TYPE_MISMATCH,
            )
        return anime_list_entry_to_current_state(entry)
    if not isinstance(entry, MangaListEntry):
        raise DomainValidationError(
            "Expected MangaListEntry for manga media type",
            code=DomainErrorCode.MEDIA_TYPE_MISMATCH,
        )
    return manga_list_entry_to_current_state(entry)
