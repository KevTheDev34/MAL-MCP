"""Unit tests for desired-state calculation."""

from __future__ import annotations

import pytest

from backend.app.commands.propose import calculate_proposed_state, is_noop_change
from backend.app.domain.enums import (
    AnimeStatus,
    DomainErrorCode,
    MangaStatus,
    MediaType,
    PlanWarningCode,
)
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.requests import RequestedChange
from backend.app.domain.state import CurrentListState


def _anime_media(**kwargs: object) -> ResolvedMedia:
    defaults: dict[str, object] = {
        "mal_id": 9253,
        "media_type": MediaType.ANIME,
        "canonical_title": "Steins;Gate",
        "total_episodes": 24,
        "confidence": 0.95,
        "publication_status": "finished_airing",
    }
    defaults.update(kwargs)
    return ResolvedMedia.model_validate(defaults)


def _manga_media(**kwargs: object) -> ResolvedMedia:
    defaults: dict[str, object] = {
        "mal_id": 642,
        "media_type": MediaType.MANGA,
        "canonical_title": "Monster",
        "total_chapters": 162,
        "total_volumes": 18,
        "confidence": 0.95,
        "publication_status": "finished",
    }
    defaults.update(kwargs)
    return ResolvedMedia.model_validate(defaults)


def test_set_score_and_status_completed_fills_total() -> None:
    current = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        episode_progress=10,
    )
    requested = RequestedChange(
        title="Steins;Gate",
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=9,
    )
    after, warnings = calculate_proposed_state(
        requested=requested,
        media=_anime_media(),
        current=current,
    )
    assert after.status is AnimeStatus.COMPLETED
    assert after.score == 9
    assert after.episode_progress == 24
    codes = {w.code for w in warnings}
    assert PlanWarningCode.STATUS_OVERWRITE in codes
    assert PlanWarningCode.PROGRESS_OVERWRITE not in codes


def test_score_overwrite_warning() -> None:
    current = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    requested = RequestedChange(
        title="Steins;Gate",
        media_type=MediaType.ANIME,
        score=7,
    )
    after, warnings = calculate_proposed_state(
        requested=requested,
        media=_anime_media(),
        current=current,
    )
    assert after.score == 7
    assert any(w.code is PlanWarningCode.SCORE_OVERWRITE for w in warnings)


def test_progress_reduction_warning() -> None:
    current = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        episode_progress=17,
    )
    requested = RequestedChange(
        title="Monster",
        media_type=MediaType.ANIME,
        episode_progress=10,
    )
    _, warnings = calculate_proposed_state(
        requested=requested,
        media=_anime_media(mal_id=1, canonical_title="Monster", total_episodes=74),
        current=current,
    )
    assert any(w.code is PlanWarningCode.PROGRESS_OVERWRITE for w in warnings)


def test_progress_exceeds_total_rejected() -> None:
    current = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        episode_progress=1,
    )
    requested = RequestedChange(
        title="Steins;Gate",
        media_type=MediaType.ANIME,
        episode_progress=99,
    )
    with pytest.raises(DomainValidationError) as exc:
        calculate_proposed_state(
            requested=requested,
            media=_anime_media(),
            current=current,
        )
    assert exc.value.code is DomainErrorCode.PROGRESS_EXCEEDS_TOTAL


def test_completed_unknown_total_warns_and_does_not_fabricate() -> None:
    current = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        episode_progress=3,
    )
    requested = RequestedChange(
        title="Airing Show",
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
    )
    after, warnings = calculate_proposed_state(
        requested=requested,
        media=_anime_media(
            total_episodes=None,
            publication_status="currently_airing",
        ),
        current=current,
    )
    assert after.episode_progress == 3
    codes = {w.code for w in warnings}
    assert PlanWarningCode.UNKNOWN_COMPLETION_TOTAL in codes
    assert PlanWarningCode.ONGOING_COMPLETED in codes


def test_not_on_list_warning_and_implicit_watching() -> None:
    current = CurrentListState(media_type=MediaType.ANIME, is_on_list=False)
    requested = RequestedChange(
        title="Steins;Gate",
        media_type=MediaType.ANIME,
        episode_progress=5,
    )
    after, warnings = calculate_proposed_state(
        requested=requested,
        media=_anime_media(),
        current=current,
    )
    assert after.status is AnimeStatus.WATCHING
    assert after.episode_progress == 5
    assert any(w.code is PlanWarningCode.NOT_PREVIOUSLY_ON_LIST for w in warnings)


def test_manga_completed_fills_known_totals() -> None:
    current = CurrentListState(
        media_type=MediaType.MANGA,
        is_on_list=True,
        status=MangaStatus.READING,
        chapter_progress=10,
        volume_progress=1,
    )
    requested = RequestedChange(
        title="Monster",
        media_type=MediaType.MANGA,
        status=MangaStatus.COMPLETED,
    )
    after, _ = calculate_proposed_state(
        requested=requested,
        media=_manga_media(),
        current=current,
    )
    assert after.chapter_progress == 162
    assert after.volume_progress == 18


def test_noop_detection() -> None:
    current = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.COMPLETED,
        score=9,
        episode_progress=24,
    )
    requested = RequestedChange(
        title="Steins;Gate",
        media_type=MediaType.ANIME,
        status=AnimeStatus.COMPLETED,
        score=9,
    )
    after, _ = calculate_proposed_state(
        requested=requested,
        media=_anime_media(),
        current=current,
    )
    assert is_noop_change(before=current, after=after)


def test_preserve_unrequested_fields() -> None:
    current = CurrentListState(
        media_type=MediaType.ANIME,
        is_on_list=True,
        status=AnimeStatus.WATCHING,
        score=8,
        episode_progress=12,
    )
    requested = RequestedChange(
        title="Steins;Gate",
        media_type=MediaType.ANIME,
        episode_progress=13,
    )
    after, _ = calculate_proposed_state(
        requested=requested,
        media=_anime_media(),
        current=current,
    )
    assert after.score == 8
    assert after.status is AnimeStatus.WATCHING
    assert after.episode_progress == 13
