"""Pure desired-state calculation for planned MAL list changes."""

from __future__ import annotations

from backend.app.commands.models import warning
from backend.app.domain.enums import (
    AnimeStatus,
    DomainErrorCode,
    MangaStatus,
    MediaType,
    PlanWarningCode,
)
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.plans import PlanWarning
from backend.app.domain.requests import RequestedChange
from backend.app.domain.state import CurrentListState, ProposedListState

_ONGOING_STATUSES = frozenset(
    {
        "currently_airing",
        "currently_publishing",
    }
)


def calculate_proposed_state(
    *,
    requested: RequestedChange,
    media: ResolvedMedia,
    current: CurrentListState,
) -> tuple[ProposedListState, list[PlanWarning]]:
    """Apply a requested change onto a normalized current state.

    Returns the proposed end state and typed warnings. Raises
    ``DomainValidationError`` for impossible or contradictory targets.
    """
    if current.media_type != media.media_type:
        raise DomainValidationError(
            "Current state media_type must match resolved media",
            code=DomainErrorCode.MEDIA_TYPE_MISMATCH,
        )

    _validate_request_for_media(requested, media.media_type)

    status = current.status
    score = current.score
    episode_progress = current.episode_progress
    chapter_progress = current.chapter_progress
    volume_progress = current.volume_progress
    warnings: list[PlanWarning] = []

    if not current.is_on_list:
        warnings.append(
            warning(
                PlanWarningCode.NOT_PREVIOUSLY_ON_LIST,
                "Title is not currently on the MAL list and will be added",
            )
        )

    if requested.status is not None:
        if (
            current.is_on_list
            and current.status is not None
            and current.status != requested.status
        ):
            warnings.append(
                warning(
                    PlanWarningCode.STATUS_OVERWRITE,
                    f"Existing status {current.status.value!r} will be changed to "
                    f"{str(requested.status)!r}",
                    field="status",
                )
            )
        status = requested.status

    if requested.score is not None:
        if current.score is not None and current.score != requested.score:
            warnings.append(
                warning(
                    PlanWarningCode.SCORE_OVERWRITE,
                    f"Existing score {current.score} will be overwritten with "
                    f"{requested.score}",
                    field="score",
                )
            )
        score = requested.score

    if media.media_type is MediaType.ANIME:
        episode_progress, status, more = _apply_anime_progress(
            requested=requested,
            media=media,
            current=current,
            status=status,
            episode_progress=episode_progress,
        )
        warnings.extend(more)
    else:
        chapter_progress, volume_progress, status, more = _apply_manga_progress(
            requested=requested,
            media=media,
            current=current,
            status=status,
            chapter_progress=chapter_progress,
            volume_progress=volume_progress,
        )
        warnings.extend(more)

    if status is not None and str(status) == "completed":
        warnings.extend(_completion_warnings(media=media, requested=requested))
        if media.media_type is MediaType.ANIME:
            episode_progress = _fill_total_if_known(
                current_progress=episode_progress,
                total=media.total_episodes,
                requested_explicit=requested.episode_progress is not None,
            )
        else:
            chapter_progress = _fill_total_if_known(
                current_progress=chapter_progress,
                total=media.total_chapters,
                requested_explicit=requested.chapter_progress is not None,
            )
            volume_progress = _fill_total_if_known(
                current_progress=volume_progress,
                total=media.total_volumes,
                requested_explicit=requested.volume_progress is not None,
            )

    # Implicit watching/reading when progress is set without status.
    if status is None:
        if media.media_type is MediaType.ANIME and (
            requested.episode_progress is not None
            or (episode_progress is not None and not current.is_on_list)
        ):
            status = AnimeStatus.WATCHING
        elif media.media_type is MediaType.MANGA and (
            requested.chapter_progress is not None
            or requested.volume_progress is not None
            or (
                (chapter_progress is not None or volume_progress is not None)
                and not current.is_on_list
            )
        ):
            status = MangaStatus.READING

    if status is None and not current.is_on_list:
        raise DomainValidationError(
            "Adding a title to the list requires a status or progress field",
            code=DomainErrorCode.NO_MUTABLE_FIELDS,
        )

    return (
        ProposedListState(
            media_type=media.media_type,
            status=status,
            score=score,
            episode_progress=(
                episode_progress if media.media_type is MediaType.ANIME else None
            ),
            chapter_progress=(
                chapter_progress if media.media_type is MediaType.MANGA else None
            ),
            volume_progress=(
                volume_progress if media.media_type is MediaType.MANGA else None
            ),
        ),
        warnings,
    )


def is_noop_change(*, before: CurrentListState, after: ProposedListState) -> bool:
    """True when the proposed snapshot matches the current mutable fields."""
    return (
        before.status == after.status
        and before.score == after.score
        and before.episode_progress == after.episode_progress
        and before.chapter_progress == after.chapter_progress
        and before.volume_progress == after.volume_progress
        and before.is_on_list
    )


def _validate_request_for_media(
    requested: RequestedChange,
    media_type: MediaType,
) -> None:
    if media_type is MediaType.ANIME:
        if (
            requested.chapter_progress is not None
            or requested.volume_progress is not None
        ):
            raise DomainValidationError(
                "Anime changes cannot include chapter or volume progress",
                code=DomainErrorCode.ANIME_CHAPTER_PROGRESS,
            )
        if requested.status is not None:
            try:
                AnimeStatus(str(requested.status))
            except ValueError as exc:
                raise DomainValidationError(
                    "Anime changes require an anime list status",
                    code=DomainErrorCode.MEDIA_STATUS_MISMATCH,
                    field="status",
                ) from exc
    else:
        if requested.episode_progress is not None:
            raise DomainValidationError(
                "Manga changes cannot include episode progress",
                code=DomainErrorCode.MANGA_EPISODE_PROGRESS,
                field="episode_progress",
            )
        if requested.status is not None:
            try:
                MangaStatus(str(requested.status))
            except ValueError as exc:
                raise DomainValidationError(
                    "Manga changes require a manga list status",
                    code=DomainErrorCode.MEDIA_STATUS_MISMATCH,
                    field="status",
                ) from exc


def _apply_anime_progress(
    *,
    requested: RequestedChange,
    media: ResolvedMedia,
    current: CurrentListState,
    status: AnimeStatus | MangaStatus | None,
    episode_progress: int | None,
) -> tuple[int | None, AnimeStatus | MangaStatus | None, list[PlanWarning]]:
    warnings: list[PlanWarning] = []
    if requested.episode_progress is None:
        return episode_progress, status, warnings

    total = media.total_episodes
    if total is not None and total > 0 and requested.episode_progress > total:
        raise DomainValidationError(
            (
                f"Episode progress {requested.episode_progress} "
                f"exceeds known total {total}"
            ),
            code=DomainErrorCode.PROGRESS_EXCEEDS_TOTAL,
            field="episode_progress",
        )

    if (
        current.episode_progress is not None
        and requested.episode_progress < current.episode_progress
    ):
        warnings.append(
            warning(
                PlanWarningCode.PROGRESS_OVERWRITE,
                f"Episode progress will be reduced from {current.episode_progress} "
                f"to {requested.episode_progress}",
                field="episode_progress",
            )
        )
    elif (
        current.episode_progress is not None
        and requested.episode_progress != current.episode_progress
    ):
        warnings.append(
            warning(
                PlanWarningCode.PROGRESS_OVERWRITE,
                f"Episode progress will change from {current.episode_progress} "
                f"to {requested.episode_progress}",
                field="episode_progress",
            )
        )

    return requested.episode_progress, status, warnings


def _apply_manga_progress(
    *,
    requested: RequestedChange,
    media: ResolvedMedia,
    current: CurrentListState,
    status: AnimeStatus | MangaStatus | None,
    chapter_progress: int | None,
    volume_progress: int | None,
) -> tuple[
    int | None,
    int | None,
    AnimeStatus | MangaStatus | None,
    list[PlanWarning],
]:
    warnings: list[PlanWarning] = []

    if requested.chapter_progress is not None:
        total = media.total_chapters
        if total is not None and total > 0 and requested.chapter_progress > total:
            raise DomainValidationError(
                (
                    f"Chapter progress {requested.chapter_progress} "
                    f"exceeds known total {total}"
                ),
                code=DomainErrorCode.PROGRESS_EXCEEDS_TOTAL,
                field="chapter_progress",
            )
        if (
            current.chapter_progress is not None
            and requested.chapter_progress < current.chapter_progress
        ):
            warnings.append(
                warning(
                    PlanWarningCode.PROGRESS_OVERWRITE,
                    f"Chapter progress will be reduced from {current.chapter_progress} "
                    f"to {requested.chapter_progress}",
                    field="chapter_progress",
                )
            )
        elif (
            current.chapter_progress is not None
            and requested.chapter_progress != current.chapter_progress
        ):
            warnings.append(
                warning(
                    PlanWarningCode.PROGRESS_OVERWRITE,
                    f"Chapter progress will change from {current.chapter_progress} "
                    f"to {requested.chapter_progress}",
                    field="chapter_progress",
                )
            )
        chapter_progress = requested.chapter_progress

    if requested.volume_progress is not None:
        total = media.total_volumes
        if total is not None and total > 0 and requested.volume_progress > total:
            raise DomainValidationError(
                (
                    f"Volume progress {requested.volume_progress} "
                    f"exceeds known total {total}"
                ),
                code=DomainErrorCode.PROGRESS_EXCEEDS_TOTAL,
                field="volume_progress",
            )
        if (
            current.volume_progress is not None
            and requested.volume_progress < current.volume_progress
        ):
            warnings.append(
                warning(
                    PlanWarningCode.PROGRESS_OVERWRITE,
                    f"Volume progress will be reduced from {current.volume_progress} "
                    f"to {requested.volume_progress}",
                    field="volume_progress",
                )
            )
        elif (
            current.volume_progress is not None
            and requested.volume_progress != current.volume_progress
        ):
            warnings.append(
                warning(
                    PlanWarningCode.PROGRESS_OVERWRITE,
                    f"Volume progress will change from {current.volume_progress} "
                    f"to {requested.volume_progress}",
                    field="volume_progress",
                )
            )
        volume_progress = requested.volume_progress

    return chapter_progress, volume_progress, status, warnings


def _fill_total_if_known(
    *,
    current_progress: int | None,
    total: int | None,
    requested_explicit: bool,
) -> int | None:
    if requested_explicit:
        return current_progress
    if total is not None and total > 0:
        return total
    return current_progress


def _completion_warnings(
    *,
    media: ResolvedMedia,
    requested: RequestedChange,
) -> list[PlanWarning]:
    warnings: list[PlanWarning] = []
    pub = (media.publication_status or "").lower()
    if pub in _ONGOING_STATUSES:
        warnings.append(
            warning(
                PlanWarningCode.ONGOING_COMPLETED,
                (
                    "Title appears to still be airing or publishing "
                    "and is being marked completed"
                ),
                field="status",
            )
        )

    if media.media_type is MediaType.ANIME:
        total = media.total_episodes
        explicit = requested.episode_progress is not None
    else:
        # Unknown if both chapter and volume totals are missing/zero.
        totals = [media.total_chapters, media.total_volumes]
        total = next((t for t in totals if t is not None and t > 0), None)
        explicit = (
            requested.chapter_progress is not None
            or requested.volume_progress is not None
        )

    if (total is None or total <= 0) and not explicit:
        warnings.append(
            warning(
                PlanWarningCode.UNKNOWN_COMPLETION_TOTAL,
                "Completion total is unknown; progress will not be fabricated",
                field="status",
            )
        )
    return warnings
