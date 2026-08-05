"""Pure deterministic candidate scoring for title resolution."""

from __future__ import annotations

import re

from backend.app.domain.enums import MediaType
from backend.app.domain.media import ResolvedMedia
from backend.app.resolver.models import TitleHints
from backend.app.resolver.normalize import (
    normalize_for_comparison,
    token_containment,
    token_jaccard,
)
from backend.app.resolver.policy import DEFAULT_RESOLVER_POLICY, ResolverPolicy

_SEASON_IN_TITLE_RE = re.compile(
    r"(?:season\s+(\d+)|s(\d+)\b|(\d+)(?:st|nd|rd|th)\s+season)",
    re.IGNORECASE,
)

_MOVIE_FORMATS = frozenset({"movie"})
_TV_FORMATS = frozenset({"tv"})
_SPECIAL_FORMATS = frozenset({"ova", "ona", "special", "music"})


def score_candidate(
    *,
    query: str,
    hints: TitleHints,
    media: ResolvedMedia,
    alias_match: bool = False,
    existing_list_match: bool = False,
    requested_media_type: MediaType | None = None,
    requested_format: str | None = None,
) -> tuple[float, list[str], list[str]]:
    """Return ``(raw_score, positive_reasons, penalties)``."""
    positives: list[str] = []
    penalties: list[str] = []
    score = 0.0

    query_cmp = normalize_for_comparison(query)
    remaining_cmp = normalize_for_comparison(hints.remaining_title)
    comparison_queries = {q for q in (query_cmp, remaining_cmp) if q}

    canonical_cmp = normalize_for_comparison(media.canonical_title)
    english_cmp = (
        normalize_for_comparison(media.english_title) if media.english_title else ""
    )
    alt_cmps = [normalize_for_comparison(t) for t in media.alternative_titles]

    if alias_match:
        score += 50
        positives.append("alias_exact")

    matched_exact = False
    for q in comparison_queries:
        if q and q == canonical_cmp:
            score += 40
            positives.append("exact_canonical")
            matched_exact = True
            break
    if not matched_exact:
        for q in comparison_queries:
            if q and english_cmp and q == english_cmp:
                score += 38
                positives.append("exact_english")
                matched_exact = True
                break
    if not matched_exact:
        for q in comparison_queries:
            if q and q in alt_cmps:
                score += 35
                positives.append("exact_alternative")
                matched_exact = True
                break
    if not matched_exact:
        for q in comparison_queries:
            title_fields = [canonical_cmp, english_cmp, *alt_cmps]
            if q and any(q == field for field in title_fields if field):
                score += 30
                positives.append("normalized_exact")
                matched_exact = True
                break

    if not matched_exact:
        best_sim = 0.0
        for q in comparison_queries:
            for field in (canonical_cmp, english_cmp, *alt_cmps):
                if not field:
                    continue
                sim = max(token_jaccard(q, field), token_containment(q, field))
                best_sim = max(best_sim, sim)
        if best_sim >= 0.85:
            score += 25
            positives.append("strong_token_similarity")
        elif best_sim >= 0.65:
            score += 20
            positives.append("token_similarity")
        elif best_sim >= 0.45:
            score += 15
            positives.append("partial_token_similarity")
        elif best_sim > 0:
            score -= 10
            penalties.append("weak_partial_title")

    effective_year = hints.release_year
    if effective_year is not None and media.release_year is not None:
        if media.release_year == effective_year:
            score += 15
            positives.append("year_match")
        else:
            score -= 20
            penalties.append("year_conflict")

    effective_season = hints.season_number
    if effective_season is not None:
        season_in_titles = _season_numbers_in_text(
            " ".join(
                filter(
                    None,
                    [
                        media.canonical_title,
                        media.english_title,
                        *media.alternative_titles,
                    ],
                )
            )
        )
        if effective_season in season_in_titles:
            score += 15
            positives.append("season_match")
        elif season_in_titles and effective_season not in season_in_titles:
            score -= 25
            penalties.append("season_conflict")

    effective_format = requested_format or hints.media_format
    media_format = (media.media_format or "").lower()
    if effective_format and media_format:
        if media_format == effective_format:
            score += 10
            positives.append("format_match")
        elif _is_movie_tv_conflict(effective_format, media_format):
            score -= 25
            penalties.append("movie_tv_conflict")
        elif effective_format in _SPECIAL_FORMATS or media_format in _SPECIAL_FORMATS:
            if effective_format != media_format:
                score -= 20
                penalties.append("special_format_conflict")
        else:
            score -= 20
            penalties.append("format_conflict")

    effective_type = requested_media_type or hints.media_type
    if effective_type is not None:
        if media.media_type == effective_type:
            score += 10
            positives.append("media_type_match")
        else:
            score -= 30
            penalties.append("anime_manga_conflict")

    if (
        effective_format in _TV_FORMATS
        and media_format in _SPECIAL_FORMATS
    ):
        score -= 15
        penalties.append("special_vs_tv")

    if existing_list_match:
        score += 5
        positives.append("existing_list_match")

    return score, positives, penalties


def compute_confidence(
    *,
    top_score: float,
    second_score: float | None,
    policy: ResolverPolicy | None = None,
) -> float:
    """Normalize raw score and runner-up margin into ``[0, 1]`` confidence."""
    policy = policy or DEFAULT_RESOLVER_POLICY
    span = policy.score_ceiling - policy.score_floor
    if span <= 0:
        return 0.0
    abs_conf = _clamp((top_score - policy.score_floor) / span, 0.0, 1.0)
    second = policy.score_floor if second_score is None else second_score
    margin = top_score - second
    margin_factor = _clamp(margin / policy.margin_full_credit, 0.0, 1.0)
    margin_weight = 1.0 - policy.abs_weight
    confidence = abs_conf * (policy.abs_weight + margin_weight * margin_factor)
    return round(_clamp(confidence, 0.0, 1.0), 4)


def candidate_sort_key(
    raw_score: float,
    media_type: MediaType,
    mal_id: int,
) -> tuple[float, int, int]:
    """Stable sort key: score desc, then anime-before-manga for stability only."""
    type_order = 0 if media_type is MediaType.ANIME else 1
    return (-raw_score, type_order, mal_id)


def _season_numbers_in_text(text: str) -> set[int]:
    found: set[int] = set()
    for match in _SEASON_IN_TITLE_RE.finditer(text):
        for group in match.groups():
            if group is not None:
                found.add(int(group))
    # Roman / digit suffixes like "II" already expanded in comparison elsewhere;
    # also detect trailing " 2" after common season words handled above.
    cmp = normalize_for_comparison(text)
    if re.search(r"\b2\b", cmp) and "season" in cmp:
        found.add(2)
    return found


def _is_movie_tv_conflict(expected: str, actual: str) -> bool:
    return (expected in _MOVIE_FORMATS and actual in _TV_FORMATS) or (
        expected in _TV_FORMATS and actual in _MOVIE_FORMATS
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
