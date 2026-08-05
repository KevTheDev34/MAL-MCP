"""Unit tests for current and proposed list states."""

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
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.tests.unit.domain_test_helpers import domain_error_from


def test_anime_current_state() -> None:
    state = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        score=8,
        episode_progress=17,
    )
    assert state.chapter_progress is None


def test_manga_current_state() -> None:
    state = CurrentListState(
        media_type=MediaType.MANGA,
        is_on_list=True,
        status=MangaStatus.READING,
        chapter_progress=65,
        volume_progress=8,
    )
    assert state.episode_progress is None


def test_not_on_list_state() -> None:
    state = CurrentListState(media_type=MediaType.ANIME, is_on_list=False)
    assert state.status is None
    assert state.score is None


def test_not_on_list_with_status_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        CurrentListState(
            media_type=MediaType.ANIME,
            is_on_list=False,
            status=AnimeStatus.WATCHING,
        )
    assert (
        domain_error_from(exc_info).code
        is DomainErrorCode.INVALID_CURRENT_LIST_STATE
    )


def test_anime_with_chapter_progress_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        CurrentListState(
            media_type=MediaType.ANIME,
            is_on_list=True,
            status=AnimeStatus.WATCHING,
            chapter_progress=1,
        )
    assert (
        domain_error_from(exc_info).code
        is DomainErrorCode.INVALID_CURRENT_LIST_STATE
    )


def test_manga_with_episode_progress_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        ProposedListState(
            media_type=MediaType.MANGA,
            status=MangaStatus.READING,
            episode_progress=1,
        )
    assert (
        domain_error_from(exc_info).code
        is DomainErrorCode.INVALID_PROPOSED_LIST_STATE
    )


def test_clear_versus_unchanged_semantics() -> None:
    before = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    unchanged = ProposedListState(
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    cleared_score = ProposedListState(
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=None,
        episode_progress=24,
    )
    assert before.score == unchanged.score
    assert before.score is not None and cleared_score.score is None
