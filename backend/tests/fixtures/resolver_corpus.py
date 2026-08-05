"""Versioned title-resolver test corpus (fixture expectations only)."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.enums import MediaType

CORPUS_VERSION = "1"


@dataclass(frozen=True)
class CorpusCase:
    """One parameterized resolution expectation."""

    name: str
    query: str
    media_type: MediaType | None
    expected_kind: str  # resolved | ambiguous | not_found
    expected_mal_id: int | None = None
    expected_media_type: MediaType | None = None
    notes: str = ""


# IDs are fixture expectations only — never hardcoded into scoring logic.
CLEAR_TITLES: list[CorpusCase] = [
    CorpusCase(
        "death_note",
        "Death Note",
        MediaType.ANIME,
        "resolved",
        1535,
        MediaType.ANIME,
    ),
    CorpusCase(
        "monster",
        "Monster",
        MediaType.ANIME,
        "resolved",
        19,
        MediaType.ANIME,
    ),
    CorpusCase(
        "cowboy_bebop",
        "Cowboy Bebop",
        MediaType.ANIME,
        "resolved",
        1,
        MediaType.ANIME,
    ),
    CorpusCase(
        "samurai_champloo",
        "Samurai Champloo",
        MediaType.ANIME,
        "resolved",
        205,
        MediaType.ANIME,
    ),
    CorpusCase(
        "steins_gate",
        "Steins;Gate",
        MediaType.ANIME,
        "resolved",
        9253,
        MediaType.ANIME,
    ),
    CorpusCase(
        "edgerunners",
        "Cyberpunk: Edgerunners",
        MediaType.ANIME,
        "resolved",
        42310,
        MediaType.ANIME,
    ),
]

ABBREVIATIONS: list[CorpusCase] = [
    CorpusCase("fma", "FMA", MediaType.ANIME, "ambiguous"),
    CorpusCase(
        "fma_brotherhood",
        "FMA Brotherhood",
        MediaType.ANIME,
        "resolved",
        5114,
        MediaType.ANIME,
    ),
    CorpusCase("hxh", "HxH", MediaType.ANIME, "ambiguous"),
    CorpusCase("bebop", "Bebop", MediaType.ANIME, "resolved", 1, MediaType.ANIME),
    CorpusCase(
        "snk",
        "Shingeki no Kyojin",
        MediaType.ANIME,
        "resolved",
        16498,
        MediaType.ANIME,
    ),
]

REMAKES: list[CorpusCase] = [
    CorpusCase("hxh_bare", "Hunter x Hunter", MediaType.ANIME, "ambiguous"),
    CorpusCase(
        "hxh_1999",
        "Hunter x Hunter 1999",
        MediaType.ANIME,
        "resolved",
        136,
        MediaType.ANIME,
    ),
    CorpusCase(
        "hxh_2011",
        "Hunter x Hunter 2011",
        MediaType.ANIME,
        "resolved",
        11061,
        MediaType.ANIME,
    ),
    CorpusCase("berserk_bare", "Berserk", None, "ambiguous"),
    CorpusCase(
        "berserk_1997",
        "Berserk 1997",
        MediaType.ANIME,
        "resolved",
        33,
        MediaType.ANIME,
    ),
]

SEASONS: list[CorpusCase] = [
    CorpusCase(
        "vinland_s2",
        "Vinland Saga season 2",
        MediaType.ANIME,
        "resolved",
        49387,
        MediaType.ANIME,
    ),
    CorpusCase(
        "aot_s3_p2",
        "Attack on Titan season 3 part 2",
        MediaType.ANIME,
        "ambiguous",
    ),
    CorpusCase(
        "mob_ii",
        "Mob Psycho 100 II",
        MediaType.ANIME,
        "resolved",
        37510,
        MediaType.ANIME,
    ),
]

MOVIES: list[CorpusCase] = [
    CorpusCase(
        "kizu_movie_2",
        "Kizumonogatari movie 2",
        MediaType.ANIME,
        "resolved",
        31738,
        MediaType.ANIME,
    ),
    CorpusCase(
        "eva_2",
        "Evangelion 2.0",
        MediaType.ANIME,
        "resolved",
        2787,
        MediaType.ANIME,
    ),
    CorpusCase(
        "mia_movie_3",
        "Made in Abyss movie 3",
        MediaType.ANIME,
        "ambiguous",
    ),
]

COLLISIONS: list[CorpusCase] = [
    CorpusCase("pluto_bare", "Pluto", None, "ambiguous"),
    CorpusCase("monster_bare", "Monster", None, "ambiguous"),
    CorpusCase(
        "death_note_manga",
        "Death Note manga",
        None,
        "resolved",
        21,
        MediaType.MANGA,
    ),
    CorpusCase(
        "pluto_anime",
        "Pluto anime",
        None,
        "resolved",
        53275,
        MediaType.ANIME,
    ),
    CorpusCase(
        "pluto_manga",
        "Pluto manga",
        None,
        "resolved",
        7675,
        MediaType.MANGA,
    ),
]

ALL_CORPUS_CASES: list[CorpusCase] = [
    *CLEAR_TITLES,
    *ABBREVIATIONS,
    *REMAKES,
    *SEASONS,
    *MOVIES,
    *COLLISIONS,
]
