"""Unit tests for resolver outcome models and request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.domain.enums import MediaType
from backend.app.domain.media import ResolvedMedia
from backend.app.resolver.errors import ResolverValidationError
from backend.app.resolver.models import (
    AmbiguousOutcome,
    NotFoundOutcome,
    ResolutionCandidate,
    ResolvedOutcome,
    ResolveTitleRequest,
    resolution_outcome_adapter,
)


def _media() -> ResolvedMedia:
    return ResolvedMedia(
        mal_id=9253,
        media_type=MediaType.ANIME,
        canonical_title="Steins;Gate",
        media_format="tv",
        release_year=2011,
        total_episodes=24,
        confidence=0.95,
        confidence_reasons=["exact_canonical"],
    )


def test_resolved_outcome_serialization() -> None:
    outcome = ResolvedOutcome(media=_media(), candidates_considered=3)
    payload = resolution_outcome_adapter.dump_python(outcome)
    assert payload["kind"] == "resolved"
    restored = resolution_outcome_adapter.validate_python(payload)
    assert isinstance(restored, ResolvedOutcome)
    assert restored.media.mal_id == 9253


def test_ambiguous_max_candidates_shape() -> None:
    candidate = ResolutionCandidate(
        media=_media(),
        raw_score=50,
        confidence=0.7,
        positive_reasons=["exact_canonical"],
        penalties=[],
        rank=1,
    )
    outcome = AmbiguousOutcome(
        query="Hunter x Hunter",
        candidates=[candidate, candidate.model_copy(update={"rank": 2})],
        reason="remake",
    )
    assert outcome.kind == "ambiguous"
    assert len(outcome.candidates) == 2


def test_not_found_outcome() -> None:
    outcome = NotFoundOutcome(
        query="zzzznotitle",
        media_type=MediaType.ANIME,
        reason="none",
    )
    assert outcome.kind == "not_found"


def test_request_rejects_blank_title() -> None:
    with pytest.raises((ResolverValidationError, ValidationError)):
        ResolveTitleRequest(title="   ")


def test_request_rejects_implausible_year() -> None:
    with pytest.raises((ResolverValidationError, ValidationError)):
        ResolveTitleRequest(title="Test", release_year=1200)


def test_request_rejects_non_positive_season() -> None:
    with pytest.raises((ResolverValidationError, ValidationError)):
        ResolveTitleRequest(title="Test", season_number=0)


def test_request_rejects_opaque_format() -> None:
    with pytest.raises((ResolverValidationError, ValidationError)):
        ResolveTitleRequest(title="Test", media_format="totally_made_up")


def test_request_accepts_known_format() -> None:
    req = ResolveTitleRequest(title="Test", media_format="TV")
    assert req.media_format == "tv"
