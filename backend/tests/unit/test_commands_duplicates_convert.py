"""Unit tests for duplicate merge and domain→MAL conversion."""

from __future__ import annotations

import pytest

from backend.app.commands.duplicates import ResolvedRequest, merge_resolved_requests
from backend.app.domain.enums import AnimeStatus, DomainErrorCode, MediaType
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.requests import RequestedChange
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.mal.domain_mapping import (
    proposed_anime_state_to_update,
    proposed_manga_state_to_update,
)


def _media(mal_id: int = 9253) -> ResolvedMedia:
    return ResolvedMedia(
        mal_id=mal_id,
        media_type=MediaType.ANIME,
        canonical_title="Steins;Gate",
        total_episodes=24,
        confidence=0.99,
    )


def test_merge_compatible_duplicate_targets() -> None:
    media = _media()
    merge = merge_resolved_requests(
        [
            ResolvedRequest(
                requested=RequestedChange(
                    title="Steins;Gate",
                    media_type=MediaType.ANIME,
                    status=AnimeStatus.COMPLETED,
                ),
                media=media,
            ),
            ResolvedRequest(
                requested=RequestedChange(
                    title="Steins Gate",
                    media_type=MediaType.ANIME,
                    score=9,
                ),
                media=media,
            ),
        ]
    )
    assert not merge.conflicts
    assert len(merge.merged) == 1
    req = merge.merged[0].requested
    assert req.status is AnimeStatus.COMPLETED
    assert req.score == 9
    assert "Steins;Gate" in merge.merged[0].source_titles
    assert "Steins Gate" in merge.merged[0].source_titles


def test_conflicting_duplicate_targets() -> None:
    media = _media()
    merge = merge_resolved_requests(
        [
            ResolvedRequest(
                requested=RequestedChange(
                    title="Steins;Gate",
                    media_type=MediaType.ANIME,
                    score=9,
                ),
                media=media,
            ),
            ResolvedRequest(
                requested=RequestedChange(
                    title="Steins Gate",
                    media_type=MediaType.ANIME,
                    score=7,
                ),
                media=media,
            ),
        ]
    )
    assert len(merge.conflicts) == 1
    assert not merge.merged


def test_proposed_anime_state_to_update_only_changed_fields() -> None:
    before = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        score=8,
        episode_progress=10,
    )
    after = ProposedListState(
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=8,
        episode_progress=24,
    )
    update = proposed_anime_state_to_update(before=before, after=after)
    data = update.model_dump(exclude_none=True)
    assert data == {"status": "completed", "num_watched_episodes": 24}


def test_proposed_anime_noop_diff_raises() -> None:
    before = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    after = ProposedListState(
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    with pytest.raises(DomainValidationError) as exc:
        proposed_anime_state_to_update(before=before, after=after)
    assert exc.value.code is DomainErrorCode.NO_MUTABLE_FIELDS


def test_proposed_manga_state_to_update() -> None:
    before = CurrentListState(
        media_type=MediaType.MANGA,
        is_on_list=False,
    )
    after = ProposedListState(
        media_type=MediaType.MANGA,
        status="completed",  # type: ignore[arg-type]
        chapter_progress=162,
        volume_progress=18,
        score=10,
    )
    update = proposed_manga_state_to_update(before=before, after=after)
    data = update.model_dump(exclude_none=True)
    assert data["status"] == "completed"
    assert data["num_chapters_read"] == 162
    assert data["num_volumes_read"] == 18
    assert data["score"] == 10
