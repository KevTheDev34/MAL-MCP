"""Unit tests for MAL transport → domain converters."""

from __future__ import annotations

import pytest

from backend.app.domain.enums import (
    AnimeStatus,
    DomainErrorCode,
    MangaStatus,
    MediaType,
)
from backend.app.domain.errors import DomainValidationError
from backend.app.mal.domain_mapping import (
    anime_details_to_resolved_media,
    anime_list_entry_to_current_state,
    list_entry_or_none_to_current_state,
    manga_details_to_resolved_media,
    manga_list_entry_to_current_state,
    not_on_list_state,
)
from backend.app.mal.models import (
    AnimeDetails,
    AnimeListEntry,
    AnimeListStatus,
    MangaDetails,
    MangaListEntry,
    MangaListStatus,
)
from backend.tests.fixtures.mal_api_responses import (
    ANIME_DETAILS_WITH_LIST_STATUS,
    ANIME_NODE,
    MANGA_DETAILS_WITH_LIST_STATUS,
    MANGA_NODE,
)


def test_anime_details_conversion() -> None:
    details = AnimeDetails.model_validate(ANIME_NODE)
    media = anime_details_to_resolved_media(
        details,
        confidence=0.91,
        confidence_reasons=["exact canonical title"],
    )
    assert media.mal_id == 9253
    assert media.media_type is MediaType.ANIME
    assert media.canonical_title == "Steins;Gate"
    assert media.english_title == "Steins;Gate"
    assert media.japanese_title == "シュタインズ・ゲート"
    assert media.media_format == "tv"
    assert media.release_year == 2011
    assert media.total_episodes == 24
    assert media.total_chapters is None
    assert media.total_volumes is None
    assert "Steins Gate" in media.alternative_titles
    assert media.confidence == 0.91


def test_manga_details_conversion() -> None:
    details = MangaDetails.model_validate(MANGA_NODE)
    media = manga_details_to_resolved_media(details, confidence=0.88)
    assert media.mal_id == 642
    assert media.media_type is MediaType.MANGA
    assert media.total_chapters == 162
    assert media.total_volumes == 18
    assert media.total_episodes is None


def test_missing_totals_remain_none() -> None:
    details = AnimeDetails.model_validate(
        {
            "id": 1,
            "title": "Unknown Episodes",
            "num_episodes": None,
        }
    )
    media = anime_details_to_resolved_media(details, confidence=0.5)
    assert media.total_episodes is None


def test_missing_optional_titles() -> None:
    details = AnimeDetails.model_validate({"id": 2, "title": "Only Canonical"})
    media = anime_details_to_resolved_media(details, confidence=0.4)
    assert media.english_title is None
    assert media.japanese_title is None
    assert media.alternative_titles == []


def test_anime_list_entry_conversion() -> None:
    entry = AnimeListEntry.model_validate(
        {
            "mal_id": 9253,
            "title": "Steins;Gate",
            "list_status": ANIME_DETAILS_WITH_LIST_STATUS["my_list_status"],
        }
    )
    state = anime_list_entry_to_current_state(entry)
    assert state.is_on_list is True
    assert state.status is AnimeStatus.COMPLETED
    assert state.score == 9
    assert state.episode_progress == 24


def test_manga_list_entry_conversion() -> None:
    entry = MangaListEntry.model_validate(
        {
            "mal_id": 642,
            "title": "Monster",
            "list_status": MANGA_DETAILS_WITH_LIST_STATUS["my_list_status"],
        }
    )
    state = manga_list_entry_to_current_state(entry)
    assert state.status is MangaStatus.COMPLETED
    assert state.score == 10
    assert state.chapter_progress == 162
    assert state.volume_progress == 18


def test_score_zero_maps_to_none() -> None:
    entry = AnimeListEntry(
        mal_id=1,
        list_status=AnimeListStatus(
            status="watching",
            score=0,
            num_episodes_watched=3,
        ),
    )
    state = anime_list_entry_to_current_state(entry)
    assert state.score is None


def test_item_not_on_list() -> None:
    state = list_entry_or_none_to_current_state(MediaType.ANIME, None)
    assert state == not_on_list_state(MediaType.ANIME)
    assert state.is_on_list is False


def test_invalid_status_string_rejected() -> None:
    entry = MangaListEntry(
        mal_id=1,
        list_status=MangaListStatus(status="watching", score=5),
    )
    with pytest.raises(DomainValidationError) as exc_info:
        manga_list_entry_to_current_state(entry)
    assert exc_info.value.code is DomainErrorCode.INVALID_STATUS
