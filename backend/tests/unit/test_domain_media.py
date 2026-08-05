"""Unit tests for ResolvedMedia validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.domain.enums import DomainErrorCode, MediaType
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.tests.unit.domain_test_helpers import domain_error_from


def test_valid_anime_resolved_media() -> None:
    media = ResolvedMedia(
        mal_id=9253,
        media_type=MediaType.ANIME,
        canonical_title="Steins;Gate",
        english_title="Steins;Gate",
        total_episodes=24,
        confidence=0.95,
        confidence_reasons=["exact title"],
    )
    assert media.total_chapters is None
    assert media.confidence == 0.95


def test_valid_manga_resolved_media() -> None:
    media = ResolvedMedia(
        mal_id=642,
        media_type=MediaType.MANGA,
        canonical_title="Monster",
        total_chapters=162,
        total_volumes=18,
        confidence=1.0,
    )
    assert media.total_episodes is None


def test_invalid_mal_id_rejected() -> None:
    with pytest.raises(ValidationError):
        ResolvedMedia(
            mal_id=0,
            media_type=MediaType.ANIME,
            canonical_title="X",
            confidence=0.5,
        )


def test_empty_canonical_title_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        ResolvedMedia(
            mal_id=1,
            media_type=MediaType.ANIME,
            canonical_title="  ",
            confidence=0.5,
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.EMPTY_CANONICAL_TITLE


def test_invalid_confidence_rejected() -> None:
    with pytest.raises(ValidationError):
        ResolvedMedia(
            mal_id=1,
            media_type=MediaType.ANIME,
            canonical_title="X",
            confidence=1.5,
        )


def test_negative_totals_rejected() -> None:
    with pytest.raises(ValidationError):
        ResolvedMedia(
            mal_id=1,
            media_type=MediaType.ANIME,
            canonical_title="X",
            total_episodes=-1,
            confidence=0.5,
        )


def test_anime_with_manga_totals_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        ResolvedMedia(
            mal_id=1,
            media_type=MediaType.ANIME,
            canonical_title="X",
            total_chapters=10,
            confidence=0.5,
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.MEDIA_TOTAL_MISMATCH


def test_manga_with_episode_totals_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        ResolvedMedia(
            mal_id=1,
            media_type=MediaType.MANGA,
            canonical_title="X",
            total_episodes=12,
            confidence=0.5,
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.MEDIA_TOTAL_MISMATCH


def test_duplicate_alternative_titles_normalized() -> None:
    media = ResolvedMedia(
        mal_id=1,
        media_type=MediaType.ANIME,
        canonical_title="Steins;Gate",
        alternative_titles=[" Steins Gate ", "Steins Gate", "", "SG"],
        confidence=0.8,
    )
    assert media.alternative_titles == ["Steins Gate", "SG"]
