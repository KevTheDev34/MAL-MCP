"""User-requested MAL change before title resolution."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.enums import (
    AnimeStatus,
    DomainErrorCode,
    MangaStatus,
    MediaType,
)
from backend.app.domain.errors import DomainValidationError


def _as_status_value(status: AnimeStatus | MangaStatus) -> str:
    return str(status)


class RequestedChange(BaseModel):
    """One user-requested list change, prior to resolution and planning.

    Does not infer missing values. Media-specific progress/status rules apply
    only when ``media_type`` is known; otherwise validation is deferred.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    media_type: MediaType | None = None
    status: AnimeStatus | MangaStatus | None = None
    score: int | None = Field(default=None, ge=1, le=10)
    episode_progress: int | None = Field(default=None, ge=0)
    chapter_progress: int | None = Field(default=None, ge=0)
    volume_progress: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise DomainValidationError(
                "Title must not be empty or whitespace-only",
                code=DomainErrorCode.EMPTY_TITLE,
                field="title",
            )
        return stripped

    @model_validator(mode="after")
    def _validate_requested_change(self) -> RequestedChange:
        mutable_present = any(
            value is not None
            for value in (
                self.status,
                self.score,
                self.episode_progress,
                self.chapter_progress,
                self.volume_progress,
            )
        )
        if not mutable_present:
            raise DomainValidationError(
                "At least one mutable field must be present",
                code=DomainErrorCode.NO_MUTABLE_FIELDS,
            )

        if self.media_type is None:
            return self

        if self.media_type is MediaType.ANIME:
            if self.chapter_progress is not None:
                raise DomainValidationError(
                    "Anime requests cannot include chapter progress",
                    code=DomainErrorCode.ANIME_CHAPTER_PROGRESS,
                    field="chapter_progress",
                )
            if self.volume_progress is not None:
                raise DomainValidationError(
                    "Anime requests cannot include volume progress",
                    code=DomainErrorCode.ANIME_VOLUME_PROGRESS,
                    field="volume_progress",
                )
            if self.status is not None:
                try:
                    anime_status = AnimeStatus(_as_status_value(self.status))
                except ValueError as exc:
                    raise DomainValidationError(
                        "Anime requests require an anime list status",
                        code=DomainErrorCode.MEDIA_STATUS_MISMATCH,
                        field="status",
                    ) from exc
                object.__setattr__(self, "status", anime_status)

        if self.media_type is MediaType.MANGA:
            if self.episode_progress is not None:
                raise DomainValidationError(
                    "Manga requests cannot include episode progress",
                    code=DomainErrorCode.MANGA_EPISODE_PROGRESS,
                    field="episode_progress",
                )
            if self.status is not None:
                try:
                    manga_status = MangaStatus(_as_status_value(self.status))
                except ValueError as exc:
                    raise DomainValidationError(
                        "Manga requests require a manga list status",
                        code=DomainErrorCode.MEDIA_STATUS_MISMATCH,
                        field="status",
                    ) from exc
                object.__setattr__(self, "status", manga_status)

        return self
