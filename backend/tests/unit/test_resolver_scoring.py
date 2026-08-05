"""Unit tests for deterministic candidate scoring and confidence."""

from __future__ import annotations

from backend.app.domain.enums import MediaType
from backend.app.domain.media import ResolvedMedia
from backend.app.resolver.models import TitleHints
from backend.app.resolver.scoring import compute_confidence, score_candidate


def _media(
    *,
    mal_id: int = 1,
    title: str = "Hunter x Hunter",
    media_type: MediaType = MediaType.ANIME,
    year: int | None = 2011,
    media_format: str | None = "tv",
    english: str | None = None,
    alts: list[str] | None = None,
    episodes: int | None = 148,
) -> ResolvedMedia:
    return ResolvedMedia(
        mal_id=mal_id,
        media_type=media_type,
        canonical_title=title,
        english_title=english,
        alternative_titles=alts or [],
        media_format=media_format,
        release_year=year,
        total_episodes=episodes if media_type is MediaType.ANIME else None,
        total_chapters=None if media_type is MediaType.ANIME else 100,
        confidence=0.0,
    )


def test_exact_canonical_match() -> None:
    score, positives, _ = score_candidate(
        query="Hunter x Hunter",
        hints=TitleHints(remaining_title="Hunter x Hunter"),
        media=_media(),
    )
    assert "exact_canonical" in positives
    assert score >= 40


def test_exact_english_match() -> None:
    score, positives, _ = score_candidate(
        query="Attack on Titan",
        hints=TitleHints(remaining_title="Attack on Titan"),
        media=_media(
            title="Shingeki no Kyojin",
            english="Attack on Titan",
        ),
    )
    assert "exact_english" in positives
    assert score >= 38


def test_exact_alternative_match() -> None:
    _, positives, _ = score_candidate(
        query="FMA Brotherhood",
        hints=TitleHints(remaining_title="FMA Brotherhood"),
        media=_media(
            title="Fullmetal Alchemist: Brotherhood",
            alts=["FMA Brotherhood"],
            year=2009,
        ),
    )
    assert "exact_alternative" in positives


def test_alias_match_bonus() -> None:
    score, positives, _ = score_candidate(
        query="FMA",
        hints=TitleHints(remaining_title="FMA"),
        media=_media(title="Fullmetal Alchemist: Brotherhood", year=2009),
        alias_match=True,
    )
    assert "alias_exact" in positives
    assert score >= 50


def test_year_match_and_conflict() -> None:
    match_score, match_pos, _ = score_candidate(
        query="Hunter x Hunter 2011",
        hints=TitleHints(remaining_title="Hunter x Hunter", release_year=2011),
        media=_media(year=2011),
    )
    conflict_score, _, penalties = score_candidate(
        query="Hunter x Hunter 2011",
        hints=TitleHints(remaining_title="Hunter x Hunter", release_year=2011),
        media=_media(mal_id=2, year=1999, episodes=62),
    )
    assert "year_match" in match_pos
    assert "year_conflict" in penalties
    assert match_score > conflict_score


def test_season_match_and_conflict() -> None:
    _, positives, _ = score_candidate(
        query="Vinland Saga season 2",
        hints=TitleHints(remaining_title="Vinland Saga", season_number=2),
        media=_media(title="Vinland Saga Season 2", year=2023),
    )
    assert "season_match" in positives

    _, _, penalties = score_candidate(
        query="Vinland Saga season 2",
        hints=TitleHints(remaining_title="Vinland Saga", season_number=2),
        media=_media(title="Vinland Saga Season 1", year=2019),
    )
    assert "season_conflict" in penalties


def test_format_and_movie_tv_conflict() -> None:
    _, positives, _ = score_candidate(
        query="Kizu movie",
        hints=TitleHints(remaining_title="Kizu", media_format="movie"),
        media=_media(title="Kizumonogatari", media_format="movie", year=2016),
        requested_format="movie",
    )
    assert "format_match" in positives

    _, _, penalties = score_candidate(
        query="Kizu movie",
        hints=TitleHints(remaining_title="Kizu", media_format="movie"),
        media=_media(title="Kizumonogatari", media_format="tv", year=2016),
        requested_format="movie",
    )
    assert "movie_tv_conflict" in penalties


def test_anime_manga_conflict() -> None:
    _, _, penalties = score_candidate(
        query="Pluto",
        hints=TitleHints(remaining_title="Pluto", media_type=MediaType.MANGA),
        media=_media(title="Pluto", media_type=MediaType.ANIME, year=2023),
        requested_media_type=MediaType.MANGA,
    )
    assert "anime_manga_conflict" in penalties


def test_existing_list_bonus_is_weak() -> None:
    without, _, _ = score_candidate(
        query="Steins;Gate",
        hints=TitleHints(remaining_title="Steins;Gate"),
        media=_media(title="Steins;Gate", year=2011),
    )
    with_list, positives, _ = score_candidate(
        query="Steins;Gate",
        hints=TitleHints(remaining_title="Steins;Gate"),
        media=_media(title="Steins;Gate", year=2011),
        existing_list_match=True,
    )
    assert with_list - without == 5
    assert "existing_list_match" in positives


def test_list_bonus_does_not_override_year_conflict() -> None:
    score, _, penalties = score_candidate(
        query="Hunter x Hunter 2011",
        hints=TitleHints(remaining_title="Hunter x Hunter", release_year=2011),
        media=_media(year=1999, episodes=62),
        existing_list_match=True,
    )
    assert "year_conflict" in penalties
    assert "existing_list_match" in score_candidate(
        query="Hunter x Hunter 2011",
        hints=TitleHints(remaining_title="Hunter x Hunter", release_year=2011),
        media=_media(year=1999, episodes=62),
        existing_list_match=True,
    )[1]
    # Conflicting year still heavily penalized relative to matching year on-list.
    match_score, _, _ = score_candidate(
        query="Hunter x Hunter 2011",
        hints=TitleHints(remaining_title="Hunter x Hunter", release_year=2011),
        media=_media(year=2011),
        existing_list_match=False,
    )
    assert match_score > score


def test_confidence_high_with_margin() -> None:
    # score_ceiling default is 55; 50 with full margin → high confidence
    conf = compute_confidence(top_score=50, second_score=10)
    assert conf >= 0.90


def test_confidence_close_competitors_remain_lower() -> None:
    close = compute_confidence(top_score=50, second_score=48)
    clear = compute_confidence(top_score=50, second_score=10)
    assert close < clear


def test_confidence_single_candidate() -> None:
    conf = compute_confidence(top_score=50, second_score=None)
    assert 0.0 < conf <= 1.0
