"""Deterministic hint extraction from user title phrases."""

from __future__ import annotations

import re

from backend.app.domain.enums import MediaType
from backend.app.resolver.models import TitleHints, normalize_media_format
from backend.app.resolver.normalize import normalize_for_search
from backend.app.resolver.policy import DEFAULT_RESOLVER_POLICY

_YEAR_RE = re.compile(
    r"(?:\(|\[|\b)(?P<year>(?:19|20)\d{2})(?:\)|\]|\b)",
)
_SEASON_WORD_RE = re.compile(
    r"\bseason\s+(?P<num>\d+)\b",
    re.IGNORECASE,
)
_SEASON_COMPACT_RE = re.compile(
    r"\bs(?P<num>\d+)\b",
    re.IGNORECASE,
)
_MOVIE_NUM_RE = re.compile(
    r"\bmovie\s+(?P<num>\d+)\b",
    re.IGNORECASE,
)
_PART_NUM_RE = re.compile(
    r"\bpart\s+(?P<num>\d+)\b",
    re.IGNORECASE,
)
_MEDIA_TYPE_TRAILING_RE = re.compile(
    r"\b(?P<media>anime|manga)\s*$",
    re.IGNORECASE,
)
_MOVIE_WORD_RE = re.compile(r"\bmovie\b", re.IGNORECASE)
_TV_WORD_RE = re.compile(r"\b(?:tv|television)\b", re.IGNORECASE)
_OVA_WORD_RE = re.compile(r"\bova\b", re.IGNORECASE)
_SPECIAL_WORD_RE = re.compile(r"\bspecials?\b", re.IGNORECASE)

# Roman season suffixes like "Mob Psycho 100 II"
_ROMAN_SEASON_RE = re.compile(
    r"\s+(?P<roman>II|III|IV|V|VI|VII|VIII|IX|X)\s*$",
)
_ROMAN_MAP = {
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
}


def extract_title_hints(title: str) -> TitleHints:
    """Extract high-confidence hints without LLM judgment."""
    working = normalize_for_search(title)
    media_type: MediaType | None = None
    release_year: int | None = None
    season_number: int | None = None
    part_number: int | None = None
    media_format: str | None = None

    media_match = _MEDIA_TYPE_TRAILING_RE.search(working)
    if media_match:
        media_type = MediaType(media_match.group("media").lower())
        working = working[: media_match.start()].rstrip(" ,-:")

    year_match = _YEAR_RE.search(working)
    if year_match:
        year = int(year_match.group("year"))
        if (
            DEFAULT_RESOLVER_POLICY.min_release_year
            <= year
            <= DEFAULT_RESOLVER_POLICY.max_release_year
        ):
            release_year = year
            before = working[: year_match.start()]
            after = working[year_match.end() :]
            working = (before + after).strip(" ,-:")

    season_match = _SEASON_WORD_RE.search(working)
    if season_match:
        season_number = int(season_match.group("num"))
        working = (
            working[: season_match.start()] + working[season_match.end() :]
        ).strip(" ,-:")
    else:
        # Compact s2 only when preceded by non-empty title text
        compact = _SEASON_COMPACT_RE.search(working)
        if compact and compact.start() > 0:
            # Avoid treating "Steins" trailing letters; require whitespace before sN
            before = working[compact.start() - 1]
            if before.isspace() or before in "-:":
                season_number = int(compact.group("num"))
                working = (
                    working[: compact.start()] + working[compact.end() :]
                ).strip(" ,-:")

    if season_number is None:
        roman = _ROMAN_SEASON_RE.search(working)
        if roman:
            season_number = _ROMAN_MAP[roman.group("roman")]
            working = working[: roman.start()].rstrip(" ,-:")

    movie_num = _MOVIE_NUM_RE.search(working)
    if movie_num:
        part_number = int(movie_num.group("num"))
        media_format = "movie"
        working = (working[: movie_num.start()] + working[movie_num.end() :]).strip(
            " ,-:"
        )
    elif _MOVIE_WORD_RE.search(working):
        media_format = "movie"
        working = _MOVIE_WORD_RE.sub(" ", working)
        working = re.sub(r"\s+", " ", working).strip(" ,-:")

    part_match = _PART_NUM_RE.search(working)
    if part_match:
        part_number = int(part_match.group("num"))
        working = (working[: part_match.start()] + working[part_match.end() :]).strip(
            " ,-:"
        )

    if media_format is None:
        if _TV_WORD_RE.search(working):
            media_format = "tv"
            working = _TV_WORD_RE.sub(" ", working)
            working = re.sub(r"\s+", " ", working).strip(" ,-:")
        elif _OVA_WORD_RE.search(working):
            media_format = "ova"
            working = _OVA_WORD_RE.sub(" ", working)
            working = re.sub(r"\s+", " ", working).strip(" ,-:")
        elif _SPECIAL_WORD_RE.search(working):
            media_format = "special"
            working = _SPECIAL_WORD_RE.sub(" ", working)
            working = re.sub(r"\s+", " ", working).strip(" ,-:")

    remaining = re.sub(r"\s+", " ", working).strip(" ,-:")
    if not remaining:
        remaining = normalize_for_search(title)

    return TitleHints(
        remaining_title=remaining,
        media_type=media_type,
        release_year=release_year,
        season_number=season_number,
        part_number=part_number,
        media_format=normalize_media_format(media_format)
        if media_format
        else None,
    )
