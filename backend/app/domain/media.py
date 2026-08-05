"""Resolved MAL media after title resolution (Phase 5 contract)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.domain.enums import DomainErrorCode, MediaType
from backend.app.domain.errors import DomainValidationError


def _normalize_alternative_titles(titles: list[str]) -> list[str]:
    """Strip empties and dedupe by exact string while preserving order."""
    seen: set[str] = set()
    normalized: list[str] = []
    for title in titles:
        stripped = title.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        normalized.append(stripped)
    return normalized


class ResolvedMedia(BaseModel):
    """Exact MAL media item after title resolution.

    Confidence scoring belongs to Phase 5; this model only validates the
    contract shape and range.
    """

    model_config = ConfigDict(extra="forbid")

    mal_id: int = Field(gt=0)
    media_type: MediaType
    canonical_title: str
    english_title: str | None = None
    japanese_title: str | None = None
    alternative_titles: list[str] = Field(default_factory=list)
    media_format: str | None = None
    release_year: int | None = None
    publication_status: str | None = None
    total_episodes: int | None = Field(default=None, ge=0)
    total_chapters: int | None = Field(default=None, ge=0)
    total_volumes: int | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_reasons: list[str] = Field(default_factory=list)

    @field_validator("canonical_title")
    @classmethod
    def _canonical_title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise DomainValidationError(
                "Canonical title must not be empty",
                code=DomainErrorCode.EMPTY_CANONICAL_TITLE,
                field="canonical_title",
            )
        return stripped

    @field_validator("alternative_titles")
    @classmethod
    def _normalize_alts(cls, value: list[str]) -> list[str]:
        return _normalize_alternative_titles(value)

    @model_validator(mode="after")
    def _validate_media_totals(self) -> ResolvedMedia:
        if self.media_type is MediaType.ANIME:
            if self.total_chapters is not None or self.total_volumes is not None:
                raise DomainValidationError(
                    "Anime resolved media cannot include manga totals",
                    code=DomainErrorCode.MEDIA_TOTAL_MISMATCH,
                )
        if self.media_type is MediaType.MANGA:
            if self.total_episodes is not None:
                raise DomainValidationError(
                    "Manga resolved media cannot include anime episode totals",
                    code=DomainErrorCode.MEDIA_TOTAL_MISMATCH,
                    field="total_episodes",
                )
        return self
