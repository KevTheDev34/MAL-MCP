"""Post-resolution duplicate target merge and conflict detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.domain.enums import (
    AnimeStatus,
    DomainErrorCode,
    MangaStatus,
    MediaType,
)
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.requests import RequestedChange


@dataclass
class ResolvedRequest:
    """One requested change paired with its resolved media."""

    requested: RequestedChange
    media: ResolvedMedia
    source_titles: list[str] = field(default_factory=list)


@dataclass
class MergeConflict:
    """Conflicting requests that resolved to the same MAL ID."""

    media: ResolvedMedia
    source_titles: list[str]
    requests: list[RequestedChange]
    message: str


@dataclass
class MergeResult:
    merged: list[ResolvedRequest]
    conflicts: list[MergeConflict]


def merge_resolved_requests(resolved: list[ResolvedRequest]) -> MergeResult:
    """Merge compatible requests for the same (media_type, mal_id).

    Conflicting field values for the same target produce a conflict entry and
    are excluded from ``merged`` so the planner never schedules two writes.
    """
    groups: dict[tuple[MediaType, int], list[ResolvedRequest]] = {}
    for item in resolved:
        key = (item.media.media_type, item.media.mal_id)
        groups.setdefault(key, []).append(item)

    merged: list[ResolvedRequest] = []
    conflicts: list[MergeConflict] = []

    for group in groups.values():
        if len(group) == 1:
            single = group[0]
            if not single.source_titles:
                single.source_titles = [single.requested.title]
            merged.append(single)
            continue

        try:
            combined = _merge_group(group)
        except DomainValidationError as exc:
            titles: list[str] = []
            for item in group:
                titles.extend(item.source_titles or [item.requested.title])
            conflicts.append(
                MergeConflict(
                    media=group[0].media,
                    source_titles=titles,
                    requests=[item.requested for item in group],
                    message=exc.message,
                )
            )
            continue
        merged.append(combined)

    return MergeResult(merged=merged, conflicts=conflicts)


def _merge_group(group: list[ResolvedRequest]) -> ResolvedRequest:
    media = group[0].media
    titles: list[str] = []
    status: AnimeStatus | MangaStatus | None = None
    score: int | None = None
    episode_progress: int | None = None
    chapter_progress: int | None = None
    volume_progress: int | None = None
    media_type: MediaType | None = media.media_type

    for item in group:
        req = item.requested
        titles.extend(item.source_titles or [req.title])
        status = _merge_status(status, req.status)
        score = _merge_field("score", score, req.score)
        episode_progress = _merge_field(
            "episode_progress",
            episode_progress,
            req.episode_progress,
        )
        chapter_progress = _merge_field(
            "chapter_progress",
            chapter_progress,
            req.chapter_progress,
        )
        volume_progress = _merge_field(
            "volume_progress",
            volume_progress,
            req.volume_progress,
        )
        if req.media_type is not None:
            if media_type is not None and req.media_type != media_type:
                raise DomainValidationError(
                    "Conflicting media_type for the same MAL target",
                    code=DomainErrorCode.DUPLICATE_TARGET_CONFLICT,
                    field="media_type",
                )
            media_type = req.media_type

    # Preserve first title as primary; list unique source titles.
    unique_titles = list(dict.fromkeys(titles))
    merged_request = RequestedChange(
        title=unique_titles[0],
        media_type=media.media_type,
        status=status,
        score=score,
        episode_progress=episode_progress,
        chapter_progress=chapter_progress,
        volume_progress=volume_progress,
    )
    return ResolvedRequest(
        requested=merged_request,
        media=media,
        source_titles=unique_titles,
    )


def _merge_status(
    current: AnimeStatus | MangaStatus | None,
    incoming: AnimeStatus | MangaStatus | None,
) -> AnimeStatus | MangaStatus | None:
    if incoming is None:
        return current
    if current is None:
        return incoming
    if current != incoming:
        raise DomainValidationError(
            "Conflicting values for field 'status' on the same MAL target",
            code=DomainErrorCode.DUPLICATE_TARGET_CONFLICT,
            field="status",
        )
    return current


def _merge_field[T](name: str, current: T | None, incoming: T | None) -> T | None:
    if incoming is None:
        return current
    if current is None:
        return incoming
    if current != incoming:
        raise DomainValidationError(
            f"Conflicting values for field {name!r} on the same MAL target",
            code=DomainErrorCode.DUPLICATE_TARGET_CONFLICT,
            field=name,
        )
    return current
