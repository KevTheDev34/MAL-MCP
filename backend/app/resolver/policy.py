"""Configurable limits and confidence thresholds for title resolution."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ResolverPolicy(BaseModel):
    """Typed policy for search budgets, enrichment caps, and outcomes."""

    model_config = ConfigDict(extra="forbid")

    search_limit: int = Field(default=10, ge=1, le=50)
    max_search_query_variants: int = Field(default=2, ge=1, le=5)
    max_enrich_candidates: int = Field(default=5, ge=1, le=20)
    max_ambiguity_candidates: int = Field(default=3, ge=1, le=10)
    max_mal_gets: int = Field(default=10, ge=1, le=40)

    score_floor: float = 0.0
    score_ceiling: float = 55.0
    margin_full_credit: float = Field(default=25.0, gt=0)
    abs_weight: float = Field(default=0.55, ge=0.0, le=1.0)

    resolve_min_confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    resolve_min_margin: float = Field(default=20.0, ge=0.0)
    resolve_min_raw_score: float = Field(default=40.0, ge=0.0)
    plausible_min_raw_score: float = Field(default=25.0, ge=0.0)

    min_release_year: int = 1900
    max_release_year: int = 2100


DEFAULT_RESOLVER_POLICY = ResolverPolicy()
