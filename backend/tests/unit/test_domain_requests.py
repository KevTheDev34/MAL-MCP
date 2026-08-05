"""Unit tests for RequestedChange validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.domain.enums import (
    AnimeStatus,
    DomainErrorCode,
    MangaStatus,
    MediaType,
)
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.requests import RequestedChange
from backend.tests.unit.domain_test_helpers import domain_error_from


def test_valid_anime_request() -> None:
    change = RequestedChange(
        title="  Steins;Gate  ",
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    assert change.title == "Steins;Gate"
    assert change.status is AnimeStatus.COMPLETED


def test_valid_manga_request() -> None:
    change = RequestedChange(
        title="Monster",
        media_type=MediaType.MANGA,
        status=MangaStatus.READING,
        chapter_progress=65,
        volume_progress=10,
    )
    assert change.status is MangaStatus.READING


def test_unknown_media_type_defers_cross_media_validation() -> None:
    change = RequestedChange(
        title="Pluto",
        media_type=None,
        status=AnimeStatus.COMPLETED,
        chapter_progress=1,
        episode_progress=1,
    )
    assert change.media_type is None
    assert change.chapter_progress == 1
    assert change.episode_progress == 1


def test_empty_title_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        RequestedChange(title="   ", score=8)
    assert domain_error_from(exc_info).code is DomainErrorCode.EMPTY_TITLE


def test_missing_mutable_fields_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        RequestedChange(title="Steins;Gate")
    assert domain_error_from(exc_info).code is DomainErrorCode.NO_MUTABLE_FIELDS


def test_score_below_one_rejected() -> None:
    with pytest.raises(ValidationError):
        RequestedChange(title="Steins;Gate", score=0)


def test_score_above_ten_rejected() -> None:
    with pytest.raises(ValidationError):
        RequestedChange(title="Steins;Gate", score=11)


def test_negative_progress_rejected() -> None:
    with pytest.raises(ValidationError):
        RequestedChange(title="Monster", episode_progress=-1)


def test_anime_with_chapter_progress_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        RequestedChange(
            title="Steins;Gate",
            media_type=MediaType.ANIME,
            chapter_progress=1,
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.ANIME_CHAPTER_PROGRESS


def test_anime_with_volume_progress_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        RequestedChange(
            title="Steins;Gate",
            media_type=MediaType.ANIME,
            volume_progress=1,
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.ANIME_VOLUME_PROGRESS


def test_manga_with_episode_progress_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        RequestedChange(
            title="Monster",
            media_type=MediaType.MANGA,
            episode_progress=1,
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.MANGA_EPISODE_PROGRESS


def test_anime_with_manga_only_status_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        RequestedChange(
            title="Steins;Gate",
            media_type=MediaType.ANIME,
            status=MangaStatus.READING,
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.MEDIA_STATUS_MISMATCH


def test_manga_with_anime_only_status_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        RequestedChange(
            title="Monster",
            media_type=MediaType.MANGA,
            status=AnimeStatus.WATCHING,
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.MEDIA_STATUS_MISMATCH


def test_unsupported_status_string_rejected() -> None:
    with pytest.raises(ValidationError):
        RequestedChange.model_validate(
            {
                "title": "Steins;Gate",
                "status": "not_a_real_status",
            }
        )
