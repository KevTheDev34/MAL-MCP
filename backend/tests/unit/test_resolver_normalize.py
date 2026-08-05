"""Unit tests for title normalization."""

from __future__ import annotations

import unicodedata

from backend.app.resolver.normalize import (
    expand_abbreviation,
    normalize_for_comparison,
    normalize_for_search,
    token_jaccard,
)


def test_unicode_nfkc() -> None:
    composed = unicodedata.normalize("NFD", "Café")
    assert normalize_for_comparison(composed) == normalize_for_comparison("Café")


def test_case_folding() -> None:
    assert normalize_for_comparison("Steins;Gate") == normalize_for_comparison(
        "steins;gate"
    )


def test_repeated_whitespace() -> None:
    assert normalize_for_search("Death   Note") == "Death Note"


def test_punctuation_and_apostrophes() -> None:
    assert normalize_for_comparison("JoJo's Bizarre Adventure") == (
        normalize_for_comparison("JoJos Bizarre Adventure")
    )


def test_dash_variants() -> None:
    assert normalize_for_comparison("Cyberpunk — Edgerunners") == (
        normalize_for_comparison("Cyberpunk - Edgerunners")
    )


def test_roman_numerals_expanded_in_comparison() -> None:
    assert "2" in normalize_for_comparison("Mob Psycho 100 II")


def test_season_wording_preserved_for_search() -> None:
    assert "season 2" in normalize_for_search("Vinland Saga season 2").lower()


def test_ampersand_safe_substitution() -> None:
    assert normalize_for_comparison("Tom & Jerry") == normalize_for_comparison(
        "Tom and Jerry"
    )


def test_abbreviation_expansion() -> None:
    assert expand_abbreviation("HxH") == "hunter x hunter"
    assert expand_abbreviation("FMA") == "fullmetal alchemist"


def test_meaningful_numbers_preserved() -> None:
    assert "100" in normalize_for_comparison("Mob Psycho 100")
    assert "2011" in normalize_for_search("Hunter x Hunter 2011")


def test_token_jaccard_identical() -> None:
    assert token_jaccard("Death Note", "Death Note") == 1.0
