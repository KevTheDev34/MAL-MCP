"""Unit tests for deterministic title hint extraction."""

from __future__ import annotations

from backend.app.domain.enums import MediaType
from backend.app.resolver.hints import extract_title_hints


def test_season_extraction() -> None:
    hints = extract_title_hints("Vinland Saga season 2")
    assert hints.season_number == 2
    assert "vinland saga" in hints.remaining_title.lower()


def test_year_extraction() -> None:
    hints = extract_title_hints("Hunter x Hunter 2011")
    assert hints.release_year == 2011
    assert "hunter x hunter" in hints.remaining_title.lower()


def test_berserk_year() -> None:
    hints = extract_title_hints("Berserk 1997")
    assert hints.release_year == 1997


def test_movie_number() -> None:
    hints = extract_title_hints("Kizumonogatari movie 2")
    assert hints.media_format == "movie"
    assert hints.part_number == 2


def test_media_type_trailing() -> None:
    assert extract_title_hints("Pluto manga").media_type is MediaType.MANGA
    assert extract_title_hints("Pluto anime").media_type is MediaType.ANIME


def test_roman_season_suffix() -> None:
    hints = extract_title_hints("Mob Psycho 100 II")
    assert hints.season_number == 2


def test_false_year_not_extracted_from_episode_like_number() -> None:
    hints = extract_title_hints("Episode 12 highlights")
    assert hints.release_year is None
    assert hints.season_number is None


def test_part_number() -> None:
    hints = extract_title_hints("Attack on Titan season 3 part 2")
    assert hints.season_number == 3
    assert hints.part_number == 2
