"""Unit tests for verification helpers."""

from __future__ import annotations

from backend.app.commands.verify import (
    states_equal_for_stale_check,
    verify_proposed_against_remote,
)
from backend.app.domain.enums import AnimeStatus, MediaType
from backend.app.domain.state import CurrentListState, ProposedListState


def test_verify_exact_match() -> None:
    intended = ProposedListState(
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    remote = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    result = verify_proposed_against_remote(
        intended=intended,
        remote=remote,
        media_type=MediaType.ANIME,
    )
    assert result.kind == "verified"


def test_verify_score_mismatch() -> None:
    intended = ProposedListState(
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    remote = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.COMPLETED,
        score=8,
        episode_progress=24,
    )
    result = verify_proposed_against_remote(
        intended=intended,
        remote=remote,
        media_type=MediaType.ANIME,
    )
    assert result.kind == "mismatch"
    assert "score" in result.field_mismatches


def test_verify_missing_item() -> None:
    intended = ProposedListState(
        media_type=MediaType.ANIME,
        status=AnimeStatus.WATCHING,
        episode_progress=1,
    )
    result = verify_proposed_against_remote(
        intended=intended,
        remote=None,
        media_type=MediaType.ANIME,
    )
    assert result.kind == "item_missing"


def test_stale_check_detects_progress_change() -> None:
    before = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        episode_progress=7,
    )
    observed = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        episode_progress=10,
    )
    assert not states_equal_for_stale_check(before, observed)
