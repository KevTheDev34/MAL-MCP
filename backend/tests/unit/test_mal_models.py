"""Unit tests for MAL client models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.mal.models import (
    AnimeListUpdate,
    AnimeSearchResult,
    MangaListUpdate,
    anime_list_entry_from_details,
    anime_list_entry_from_list_item,
    anime_list_entry_from_status,
)
from backend.tests.fixtures.mal_api_responses import (
    ANIME_DETAILS_WITH_LIST_STATUS,
    ANIME_DETAILS_WITHOUT_LIST_STATUS,
    ANIME_LIST_STATUS,
    ANIME_NODE,
)


def test_anime_search_release_year_and_titles() -> None:
    result = AnimeSearchResult.model_validate(ANIME_NODE)
    assert result.release_year == 2011
    assert result.english_title == "Steins;Gate"
    assert result.japanese_title == "シュタインズ・ゲート"


def test_anime_list_update_form_encoding() -> None:
    update = AnimeListUpdate(
        status="watching",
        score=8,
        num_watched_episodes=3,
        is_rewatching=False,
    )
    form = update.to_form_data()
    assert form["status"] == "watching"
    assert form["score"] == "8"
    assert form["num_watched_episodes"] == "3"
    assert form["is_rewatching"] == "false"


def test_manga_list_update_requires_field() -> None:
    with pytest.raises(ValidationError):
        MangaListUpdate()


def test_anime_list_entry_helpers() -> None:
    entry = anime_list_entry_from_status(9253, ANIME_LIST_STATUS)
    assert entry.mal_id == 9253
    assert entry.list_status.num_episodes_watched == 24

    list_entry = anime_list_entry_from_list_item(
        {"node": ANIME_NODE, "list_status": ANIME_LIST_STATUS}
    )
    assert list_entry.title == "Steins;Gate"
    assert list_entry.num_episodes == 24

    from_details = anime_list_entry_from_details(ANIME_DETAILS_WITH_LIST_STATUS)
    assert from_details is not None
    assert from_details.title == "Steins;Gate"
    assert from_details.list_status.score == 9
    assert anime_list_entry_from_details(ANIME_DETAILS_WITHOUT_LIST_STATUS) is None
