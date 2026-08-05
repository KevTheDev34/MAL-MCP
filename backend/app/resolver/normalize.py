"""Deterministic title normalization for comparison and MAL search."""

from __future__ import annotations

import re
import unicodedata

# Apostrophe / quote variants → ASCII apostrophe
_APOSTROPHE_RE = re.compile(r"[\u2018\u2019\u201A\u201B`´]")
# Hyphen / dash variants → ASCII hyphen
_DASH_RE = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212―‒–—]")
# Punctuation removed for comparison (keep alphanumerics and spaces)
_COMPARISON_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_COLON_SPACE_RE = re.compile(r"\s*:\s*")

# Whole-token ampersand ↔ and (safe substitution for comparison)
_AMP_TOKEN_RE = re.compile(r"(?<!\w)&(?!\w)")
_AND_TOKEN_RE = re.compile(r"(?<!\w)and(?!\w)", re.IGNORECASE)

# Roman numerals commonly used in season/part suffixes
_ROMAN_TO_INT = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
}

_ORDINAL_WORDS = {
    "first": "1",
    "second": "2",
    "third": "3",
    "fourth": "4",
    "fifth": "5",
    "sixth": "6",
    "seventh": "7",
    "eighth": "8",
    "ninth": "9",
    "tenth": "10",
}

# Small abbreviation expansions used as additional search variants only.
ABBREVIATION_EXPANSIONS: dict[str, str] = {
    "fma": "fullmetal alchemist",
    "fma brotherhood": "fullmetal alchemist brotherhood",
    "hxh": "hunter x hunter",
    "snk": "shingeki no kyojin",
    "aot": "attack on titan",
    "bebop": "cowboy bebop",
}


def normalize_for_search(text: str) -> str:
    """Light normalization suitable for MAL search queries.

    Preserves years, season digits, subtitle text, and meaningful numerals.
    """
    value = unicodedata.normalize("NFKC", text)
    value = _APOSTROPHE_RE.sub("'", value)
    value = _DASH_RE.sub("-", value)
    value = _COLON_SPACE_RE.sub(": ", value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value


def normalize_for_comparison(text: str) -> str:
    """Aggressive normalization for equality / similarity scoring.

    Does not invent MAL identity; only prepares strings for comparison.
    """
    value = unicodedata.normalize("NFKC", text)
    value = _APOSTROPHE_RE.sub("", value)
    value = value.replace("'", "")
    value = _DASH_RE.sub("-", value)
    value = _COLON_SPACE_RE.sub(" ", value)
    value = _AMP_TOKEN_RE.sub(" and ", value)
    value = value.casefold()
    value = _COMPARISON_PUNCT_RE.sub(" ", value)
    value = _expand_ordinals_and_romans(value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value


def expand_abbreviation(text: str) -> str | None:
    """Return an expanded form for a known abbreviation, else None."""
    key = normalize_for_comparison(text)
    return ABBREVIATION_EXPANSIONS.get(key)


def comparison_tokens(text: str) -> list[str]:
    """Tokenize a comparison-normalized string."""
    normalized = normalize_for_comparison(text)
    if not normalized:
        return []
    return normalized.split(" ")


def token_jaccard(a: str, b: str) -> float:
    """Jaccard similarity over comparison tokens."""
    left = set(comparison_tokens(a))
    right = set(comparison_tokens(b))
    if not left or not right:
        return 0.0
    intersection = left & right
    union = left | right
    return len(intersection) / len(union)


def token_containment(query: str, candidate: str) -> float:
    """Fraction of query tokens present in the candidate."""
    left = set(comparison_tokens(query))
    right = set(comparison_tokens(candidate))
    if not left:
        return 0.0
    return len(left & right) / len(left)


def _expand_ordinals_and_romans(value: str) -> str:
    """Replace ordinal words and standalone roman numerals with digits."""
    tokens = value.split()
    out: list[str] = []
    for token in tokens:
        if token in _ORDINAL_WORDS:
            out.append(_ORDINAL_WORDS[token])
        elif token in _ROMAN_TO_INT and _looks_like_roman_suffix(out):
            out.append(str(_ROMAN_TO_INT[token]))
        else:
            out.append(token)
    return " ".join(out)


def _looks_like_roman_suffix(prior_tokens: list[str]) -> bool:
    """Only expand roman numerals that follow title-like context."""
    if not prior_tokens:
        return False
    # Avoid expanding lone "i" pronouns; require prior alphanumeric title token.
    return any(t.isalnum() for t in prior_tokens)
