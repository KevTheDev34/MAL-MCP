"""Title-resolution request, candidate, and outcome models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from backend.app.domain.enums import MediaType
from backend.app.domain.media import ResolvedMedia
from backend.app.resolver.errors import ResolverValidationError
from backend.app.resolver.policy import DEFAULT_RESOLVER_POLICY

ALLOWED_MEDIA_FORMATS = frozenset(
    {
        "tv",
        "movie",
        "ova",
        "ona",
        "special",
        "music",
        "manga",
        "novel",
        "one_shot",
        "doujinshi",
        "manhwa",
        "manhua",
        "oel",
        "unknown",
    }
)


def normalize_media_format(value: str | None) -> str | None:
    """Normalize and validate an optional media-format hint."""
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized:
        return None
    if normalized not in ALLOWED_MEDIA_FORMATS:
        raise ResolverValidationError(
            f"Unsupported media_format: {value!r}",
            field="media_format",
        )
    return normalized


class ResolveTitleRequest(BaseModel):
    """Typed input for title resolution."""

    model_config = ConfigDict(extra="forbid")

    title: str
    media_type: MediaType | None = None
    release_year: int | None = None
    season_number: int | None = None
    media_format: str | None = None
    allow_aliases: bool = True

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ResolverValidationError(
                "Title must not be empty or whitespace-only",
                field="title",
            )
        return stripped

    @field_validator("media_format")
    @classmethod
    def _validate_media_format(cls, value: str | None) -> str | None:
        return normalize_media_format(value)

    @model_validator(mode="after")
    def _validate_hints(self) -> ResolveTitleRequest:
        policy = DEFAULT_RESOLVER_POLICY
        if self.release_year is not None and not (
            policy.min_release_year <= self.release_year <= policy.max_release_year
        ):
            raise ResolverValidationError(
                (
                    f"release_year must be between {policy.min_release_year} "
                    f"and {policy.max_release_year}"
                ),
                field="release_year",
            )
        if self.season_number is not None and self.season_number < 1:
            raise ResolverValidationError(
                "season_number must be positive",
                field="season_number",
            )
        return self


class TitleHints(BaseModel):
    """Deterministic hints extracted from a title phrase."""

    model_config = ConfigDict(extra="forbid")

    remaining_title: str
    media_type: MediaType | None = None
    release_year: int | None = None
    season_number: int | None = None
    part_number: int | None = None
    media_format: str | None = None


class ResolutionCandidate(BaseModel):
    """Scored media candidate returned by the resolver."""

    model_config = ConfigDict(extra="forbid")

    media: ResolvedMedia
    raw_score: float
    confidence: float = Field(ge=0.0, le=1.0)
    positive_reasons: list[str] = Field(default_factory=list)
    penalties: list[str] = Field(default_factory=list)
    alias_match: bool = False
    existing_list_match: bool = False
    rank: int = Field(ge=1)


class ResolvedOutcome(BaseModel):
    """One high-confidence match."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["resolved"] = "resolved"
    media: ResolvedMedia
    candidates_considered: int = Field(ge=0)


class AmbiguousOutcome(BaseModel):
    """Several plausible candidates requiring clarification."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ambiguous"] = "ambiguous"
    query: str
    candidates: list[ResolutionCandidate]
    reason: str


class NotFoundOutcome(BaseModel):
    """No plausible match."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["not_found"] = "not_found"
    query: str
    media_type: MediaType | None = None
    reason: str


ResolutionOutcome = Annotated[
    ResolvedOutcome | AmbiguousOutcome | NotFoundOutcome,
    Field(discriminator="kind"),
]

resolution_outcome_adapter: TypeAdapter[ResolutionOutcome] = TypeAdapter(
    ResolutionOutcome
)
