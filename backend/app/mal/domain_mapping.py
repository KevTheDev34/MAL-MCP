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
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.mal.models import (
    AlternativeTitles,
    AnimeDetails,
    AnimeListEntry,
    AnimeListUpdate,
    AnimeSearchResult,
    MangaDetails,
    MangaListEntry,
    MangaListUpdate,
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
        publication_status=details.status,
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
        publication_status=details.status,
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


def proposed_anime_state_to_update(
    *,
    before: CurrentListState,
    after: ProposedListState,
) -> AnimeListUpdate:
    """Diff before/after anime domain states into a typed MAL update patch."""
    if after.media_type is not MediaType.ANIME:
        raise DomainValidationError(
            "Anime update conversion requires anime proposed state",
            code=DomainErrorCode.MEDIA_TYPE_MISMATCH,
        )
    fields: dict[str, object] = {}
    if before.status != after.status and after.status is not None:
        fields["status"] = str(after.status)
    if before.score != after.score:
        if after.score is not None:
            fields["score"] = after.score
        elif before.score is not None:
            fields["score"] = 0
    if before.episode_progress != after.episode_progress:
        if after.episode_progress is not None:
            fields["num_watched_episodes"] = after.episode_progress
        elif before.episode_progress is not None:
            fields["num_watched_episodes"] = 0
    if not fields:
        raise DomainValidationError(
            "No anime fields differ between before and after states",
            code=DomainErrorCode.NO_MUTABLE_FIELDS,
        )
    return AnimeListUpdate.model_validate(fields)


def proposed_manga_state_to_update(
    *,
    before: CurrentListState,
    after: ProposedListState,
) -> MangaListUpdate:
    """Diff before/after manga domain states into a typed MAL update patch."""
    if after.media_type is not MediaType.MANGA:
        raise DomainValidationError(
            "Manga update conversion requires manga proposed state",
            code=DomainErrorCode.MEDIA_TYPE_MISMATCH,
        )
    fields: dict[str, object] = {}
    if before.status != after.status and after.status is not None:
        fields["status"] = str(after.status)
    if before.score != after.score:
        if after.score is not None:
            fields["score"] = after.score
        elif before.score is not None:
            fields["score"] = 0
    if before.chapter_progress != after.chapter_progress:
        if after.chapter_progress is not None:
            fields["num_chapters_read"] = after.chapter_progress
        elif before.chapter_progress is not None:
            fields["num_chapters_read"] = 0
    if before.volume_progress != after.volume_progress:
        if after.volume_progress is not None:
            fields["num_volumes_read"] = after.volume_progress
        elif before.volume_progress is not None:
            fields["num_volumes_read"] = 0
    if not fields:
        raise DomainValidationError(
            "No manga fields differ between before and after states",
            code=DomainErrorCode.NO_MUTABLE_FIELDS,
        )
    return MangaListUpdate.model_validate(fields)
