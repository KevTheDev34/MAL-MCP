"""Normalized current and proposed MAL list states."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.enums import (
    AnimeStatus,
    DomainErrorCode,
    MangaStatus,
    MediaType,
)
from backend.app.domain.errors import DomainValidationError


def _normalize_status_for_media(
    media_type: MediaType,
    status: AnimeStatus | MangaStatus | None,
) -> AnimeStatus | MangaStatus | None:
    if status is None:
        return None
    value = str(status)
    if media_type is MediaType.ANIME:
        try:
            return AnimeStatus(value)
        except ValueError as exc:
            raise DomainValidationError(
                "Anime list state requires an anime status",
                code=DomainErrorCode.MEDIA_STATUS_MISMATCH,
                field="status",
            ) from exc
    try:
        return MangaStatus(value)
    except ValueError as exc:
        raise DomainValidationError(
            "Manga list state requires a manga status",
            code=DomainErrorCode.MEDIA_STATUS_MISMATCH,
            field="status",
        ) from exc


def _validate_media_progress(
    *,
    media_type: MediaType,
    episode_progress: int | None,
    chapter_progress: int | None,
    volume_progress: int | None,
    error_code: DomainErrorCode,
) -> None:
    if media_type is MediaType.ANIME:
        if chapter_progress is not None or volume_progress is not None:
            raise DomainValidationError(
                "Anime list state cannot include chapter or volume progress",
                code=error_code,
            )
    if media_type is MediaType.MANGA and episode_progress is not None:
        raise DomainValidationError(
            "Manga list state cannot include episode progress",
            code=error_code,
        )


class CurrentListState(BaseModel):
    """Normalized representation of the user's current MAL list entry state.

    When ``is_on_list`` is False, all mutable fields must be None.
    Domain score never uses 0; unscored is represented as None.
    """

    model_config = ConfigDict(extra="forbid")

    media_type: MediaType
    is_on_list: bool
    status: AnimeStatus | MangaStatus | None = None
    score: int | None = Field(default=None, ge=1, le=10)
    episode_progress: int | None = Field(default=None, ge=0)
    chapter_progress: int | None = Field(default=None, ge=0)
    volume_progress: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_current_state(self) -> CurrentListState:
        if not self.is_on_list:
            if any(
                value is not None
                for value in (
                    self.status,
                    self.score,
                    self.episode_progress,
                    self.chapter_progress,
                    self.volume_progress,
                )
            ):
                raise DomainValidationError(
                    "Not-on-list state cannot include status, score, or progress",
                    code=DomainErrorCode.INVALID_CURRENT_LIST_STATE,
                )
            return self

        _validate_media_progress(
            media_type=self.media_type,
            episode_progress=self.episode_progress,
            chapter_progress=self.chapter_progress,
            volume_progress=self.volume_progress,
            error_code=DomainErrorCode.INVALID_CURRENT_LIST_STATE,
        )
        normalized = _normalize_status_for_media(self.media_type, self.status)
        object.__setattr__(self, "status", normalized)
        return self


class ProposedListState(BaseModel):
    """Desired end state after a planned change is applied.

    Full snapshot semantics:

    - Unchanged field: ``before.field == after.field``
    - Intentional set: ``after.field`` differs from ``before.field``
    - Intentional clear: ``before.field`` is set and ``after.field is None``
      (score/progress). Status clear is not supported in MVP.
    """

    model_config = ConfigDict(extra="forbid")

    media_type: MediaType
    status: AnimeStatus | MangaStatus | None = None
    score: int | None = Field(default=None, ge=1, le=10)
    episode_progress: int | None = Field(default=None, ge=0)
    chapter_progress: int | None = Field(default=None, ge=0)
    volume_progress: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_proposed_state(self) -> ProposedListState:
        _validate_media_progress(
            media_type=self.media_type,
            episode_progress=self.episode_progress,
            chapter_progress=self.chapter_progress,
            volume_progress=self.volume_progress,
            error_code=DomainErrorCode.INVALID_PROPOSED_LIST_STATE,
        )
        normalized = _normalize_status_for_media(self.media_type, self.status)
        object.__setattr__(self, "status", normalized)
        return self
