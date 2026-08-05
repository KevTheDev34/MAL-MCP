"""Title resolution service: normalize → alias → search → enrich → score."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.app.db.models import TitleAlias
from backend.app.domain.enums import MediaType
from backend.app.domain.media import ResolvedMedia
from backend.app.mal.client import MalClient
from backend.app.mal.domain_mapping import (
    anime_details_to_resolved_media,
    manga_details_to_resolved_media,
)
from backend.app.mal.errors import (
    MalAuthenticationError,
    MalError,
    MalNotFoundError,
    MalRateLimitError,
    MalTemporaryError,
)
from backend.app.resolver.aliases import AliasMatch, AliasService
from backend.app.resolver.errors import (
    ResolverAuthenticationError,
    ResolverEnrichmentError,
    ResolverTemporaryError,
)
from backend.app.resolver.hints import extract_title_hints
from backend.app.resolver.models import (
    AmbiguousOutcome,
    NotFoundOutcome,
    ResolutionCandidate,
    ResolutionOutcome,
    ResolvedOutcome,
    ResolveTitleRequest,
    TitleHints,
)
from backend.app.resolver.normalize import normalize_for_search
from backend.app.resolver.policy import DEFAULT_RESOLVER_POLICY, ResolverPolicy
from backend.app.resolver.scoring import (
    candidate_sort_key,
    compute_confidence,
    score_candidate,
)
from backend.app.resolver.search import (
    SearchHit,
    build_search_queries,
    enrich_hit,
    search_mal_candidates,
)

logger = logging.getLogger(__name__)


@dataclass
class _ScoredRow:
    media: ResolvedMedia
    raw_score: float
    positive_reasons: list[str]
    penalties: list[str]
    alias_match: bool
    existing_list_match: bool
    alias_row: TitleAlias | None = None


class TitleResolver:
    """Deterministic title → MAL media resolver."""

    def __init__(
        self,
        *,
        mal_client: MalClient,
        alias_service: AliasService,
        policy: ResolverPolicy | None = None,
    ) -> None:
        self._client = mal_client
        self._aliases = alias_service
        self._policy = policy or DEFAULT_RESOLVER_POLICY

    async def resolve(
        self,
        *,
        user_id: str | None,
        request: ResolveTitleRequest,
    ) -> ResolutionOutcome:
        """Resolve a user title into a typed outcome. Never writes to MAL."""
        hints = extract_title_hints(request.title)
        effective = _merge_hints(request, hints)
        request_counter = [0]
        alias_seeded: list[tuple[SearchHit, TitleAlias]] = []

        if user_id and request.allow_aliases:
            alias_seeded = await self._seed_aliases(
                user_id=user_id,
                request=request,
                effective=effective,
                request_counter=request_counter,
            )

        media_types = _media_types_for_search(effective.media_type)
        queries = build_search_queries(
            original_title=request.title,
            remaining_title=effective.remaining_title,
            max_variants=self._policy.max_search_query_variants,
        )

        hits = await search_mal_candidates(
            self._client,
            queries=queries,
            media_types=media_types,
            policy=self._policy,
            request_counter=request_counter,
        )

        # Merge alias seeds first so they participate in pre-score + enrich.
        merged: list[SearchHit] = []
        alias_by_key: dict[tuple[MediaType, int], TitleAlias] = {}
        for hit, alias_row in alias_seeded:
            key = (hit.media_type, hit.mal_id)
            alias_by_key[key] = alias_row
            merged.append(hit)
        for hit in hits:
            key = (hit.media_type, hit.mal_id)
            if key not in alias_by_key and all(
                (h.media_type, h.mal_id) != key for h in merged
            ):
                merged.append(hit)

        if not merged:
            return NotFoundOutcome(
                query=request.title,
                media_type=effective.media_type,
                reason="No MAL search results matched the query",
            )

        pre_scored = self._score_rows(
            query=request.title,
            hints=effective,
            rows=[
                _ScoredRow(
                    media=hit.media,
                    raw_score=0,
                    positive_reasons=[],
                    penalties=[],
                    alias_match=(hit.media_type, hit.mal_id) in alias_by_key,
                    existing_list_match=False,
                    alias_row=alias_by_key.get((hit.media_type, hit.mal_id)),
                )
                for hit in merged
            ],
            request=request,
        )
        pre_scored.sort(
            key=lambda row: candidate_sort_key(
                row.raw_score, row.media.media_type, row.media.mal_id
            )
        )

        to_enrich = pre_scored[: self._policy.max_enrich_candidates]
        enriched_rows: list[_ScoredRow] = []
        enrichment_failures = 0

        for row in to_enrich:
            hit = SearchHit(
                media_type=row.media.media_type,
                mal_id=row.media.mal_id,
                media=row.media,
            )
            result = await enrich_hit(
                self._client,
                hit,
                request_counter=request_counter,
                policy=self._policy,
            )
            if result is None:
                enrichment_failures += 1
                continue
            media, on_list = result
            # Soft-skip list signal when user_id is absent.
            existing = bool(on_list and user_id)
            enriched_rows.append(
                _ScoredRow(
                    media=media,
                    raw_score=0,
                    positive_reasons=[],
                    penalties=[],
                    alias_match=row.alias_match,
                    existing_list_match=existing,
                    alias_row=row.alias_row,
                )
            )

        if not enriched_rows:
            if enrichment_failures:
                raise ResolverEnrichmentError(
                    "Candidate enrichment failed for all selected candidates"
                )
            return NotFoundOutcome(
                query=request.title,
                media_type=effective.media_type,
                reason="No enrichable candidates remained",
            )

        scored = self._score_rows(
            query=request.title,
            hints=effective,
            rows=enriched_rows,
            request=request,
        )
        scored.sort(
            key=lambda row: candidate_sort_key(
                row.raw_score, row.media.media_type, row.media.mal_id
            )
        )

        outcome = self._decide_outcome(
            query=request.title,
            effective=effective,
            scored=scored,
        )

        if (
            isinstance(outcome, ResolvedOutcome)
            and scored
            and scored[0].alias_row is not None
        ):
            try:
                self._aliases.touch(scored[0].alias_row)
            except Exception:
                logger.warning("Failed to update alias last_used_at", exc_info=True)

        return outcome

    async def save_alias(
        self,
        *,
        user_id: str,
        alias: str,
        media_type: MediaType,
        mal_id: int,
        canonical_title: str,
    ) -> TitleAlias:
        """Persist a user alias after explicit clarification (later phases)."""
        return self._aliases.save(
            user_id=user_id,
            alias=alias,
            media_type=media_type,
            mal_id=mal_id,
            canonical_title=canonical_title,
        )

    async def _seed_aliases(
        self,
        *,
        user_id: str,
        request: ResolveTitleRequest,
        effective: TitleHints,
        request_counter: list[int],
    ) -> list[tuple[SearchHit, TitleAlias]]:
        matches = self._aliases.lookup(
            user_id=user_id,
            title=request.title,
            media_type=effective.media_type,
        )
        seeded: list[tuple[SearchHit, TitleAlias]] = []
        for match in matches:
            if _alias_conflicts_with_hints(match, effective):
                continue
            validated = await self._validate_alias_target(
                match, request_counter=request_counter
            )
            if validated is None:
                continue
            media, on_list = validated
            if _alias_metadata_conflicts(media, effective):
                continue
            hit = SearchHit(
                media_type=match.media_type,
                mal_id=match.mal_id,
                media=media,
                source="alias",
            )
            # on_list is unused until enrichment re-checks; keep for future.
            _ = on_list
            seeded.append((hit, match.alias))
        return seeded

    async def _validate_alias_target(
        self,
        match: AliasMatch,
        *,
        request_counter: list[int],
    ) -> tuple[ResolvedMedia, bool] | None:
        if request_counter[0] >= self._policy.max_mal_gets:
            return None
        request_counter[0] += 1
        try:
            if match.media_type is MediaType.ANIME:
                anime_details, on_list = (
                    await self._client.get_anime_resolution_context(match.mal_id)
                )
                media = anime_details_to_resolved_media(
                    anime_details, confidence=0.0, confidence_reasons=[]
                )
                return media, on_list
            manga_details, on_list = (
                await self._client.get_manga_resolution_context(match.mal_id)
            )
            media = manga_details_to_resolved_media(
                manga_details, confidence=0.0, confidence_reasons=[]
            )
            return media, on_list
        except MalNotFoundError:
            logger.info(
                "Ignoring alias to missing MAL id=%s type=%s",
                match.mal_id,
                match.media_type.value,
            )
            return None
        except MalAuthenticationError as exc:
            raise ResolverAuthenticationError(exc.message) from exc
        except (MalTemporaryError, MalRateLimitError) as exc:
            raise ResolverTemporaryError(exc.message) from exc
        except MalError:
            return None

    def _score_rows(
        self,
        *,
        query: str,
        hints: TitleHints,
        rows: list[_ScoredRow],
        request: ResolveTitleRequest,
    ) -> list[_ScoredRow]:
        scored: list[_ScoredRow] = []
        for row in rows:
            raw, positives, penalties = score_candidate(
                query=query,
                hints=hints,
                media=row.media,
                alias_match=row.alias_match,
                existing_list_match=row.existing_list_match,
                requested_media_type=request.media_type or hints.media_type,
                requested_format=request.media_format or hints.media_format,
            )
            scored.append(
                _ScoredRow(
                    media=row.media,
                    raw_score=raw,
                    positive_reasons=positives,
                    penalties=penalties,
                    alias_match=row.alias_match,
                    existing_list_match=row.existing_list_match,
                    alias_row=row.alias_row,
                )
            )
        return scored

    def _decide_outcome(
        self,
        *,
        query: str,
        effective: TitleHints,
        scored: list[_ScoredRow],
    ) -> ResolutionOutcome:
        policy = self._policy
        if not scored:
            return NotFoundOutcome(
                query=query,
                media_type=effective.media_type,
                reason="No candidates remained after scoring",
            )

        top = scored[0]
        second_score = scored[1].raw_score if len(scored) > 1 else None

        confidences: list[float] = []
        for index, row in enumerate(scored):
            if index + 1 < len(scored):
                next_score = scored[index + 1].raw_score
            else:
                next_score = None
            confidences.append(
                compute_confidence(
                    top_score=row.raw_score,
                    second_score=next_score if index == 0 else next_score,
                    policy=policy,
                )
            )
        # Ensure top confidence uses the true runner-up margin.
        confidences[0] = compute_confidence(
            top_score=top.raw_score,
            second_score=second_score,
            policy=policy,
        )

        top_confidence = confidences[0]
        margin = top.raw_score - (
            second_score if second_score is not None else policy.score_floor
        )

        candidates = [
            _to_candidate(row, confidence=confidences[i], rank=i + 1)
            for i, row in enumerate(scored)
        ]

        if (
            top_confidence >= policy.resolve_min_confidence
            and margin >= policy.resolve_min_margin
            and top.raw_score >= policy.resolve_min_raw_score
        ):
            media = candidates[0].media.model_copy(
                update={
                    "confidence": top_confidence,
                    "confidence_reasons": [
                        *top.positive_reasons,
                        *[f"penalty:{p}" for p in top.penalties],
                    ],
                }
            )
            return ResolvedOutcome(
                media=media,
                candidates_considered=len(scored),
            )

        # Sole strong candidate: no runner-up, so resolve without requiring
        # the multi-candidate confidence band (exact match alone scores ~40).
        if len(scored) == 1 and top.raw_score >= policy.resolve_min_raw_score:
            media = candidates[0].media.model_copy(
                update={
                    "confidence": max(top_confidence, policy.resolve_min_confidence),
                    "confidence_reasons": [
                        *top.positive_reasons,
                        *[f"penalty:{p}" for p in top.penalties],
                    ],
                }
            )
            return ResolvedOutcome(
                media=media,
                candidates_considered=1,
            )

        plausible = [
            c
            for c, row in zip(candidates, scored, strict=True)
            if row.raw_score >= policy.plausible_min_raw_score
        ]
        if not plausible:
            return NotFoundOutcome(
                query=query,
                media_type=effective.media_type,
                reason="No candidate cleared the minimum plausibility threshold",
            )

        if (
            len(plausible) == 1
            and scored[0].raw_score < policy.resolve_min_raw_score
        ):
            return NotFoundOutcome(
                query=query,
                media_type=effective.media_type,
                reason="Only a weak candidate was found; need more detail",
            )

        return AmbiguousOutcome(
            query=query,
            candidates=plausible[: policy.max_ambiguity_candidates],
            reason="Multiple plausible matches; clarification required",
        )


def _to_candidate(
    row: _ScoredRow,
    *,
    confidence: float,
    rank: int,
) -> ResolutionCandidate:
    media = row.media.model_copy(
        update={
            "confidence": confidence,
            "confidence_reasons": [
                *row.positive_reasons,
                *[f"penalty:{p}" for p in row.penalties],
            ],
        }
    )
    return ResolutionCandidate(
        media=media,
        raw_score=row.raw_score,
        confidence=confidence,
        positive_reasons=list(row.positive_reasons),
        penalties=list(row.penalties),
        alias_match=row.alias_match,
        existing_list_match=row.existing_list_match,
        rank=rank,
    )


def _merge_hints(request: ResolveTitleRequest, extracted: TitleHints) -> TitleHints:
    """Request fields win over extracted hints on conflict."""
    remaining = extracted.remaining_title or normalize_for_search(request.title)
    return TitleHints(
        remaining_title=remaining,
        media_type=request.media_type or extracted.media_type,
        release_year=request.release_year
        if request.release_year is not None
        else extracted.release_year,
        season_number=request.season_number
        if request.season_number is not None
        else extracted.season_number,
        part_number=extracted.part_number,
        media_format=request.media_format or extracted.media_format,
    )


def _media_types_for_search(media_type: MediaType | None) -> list[MediaType]:
    if media_type is MediaType.ANIME:
        return [MediaType.ANIME]
    if media_type is MediaType.MANGA:
        return [MediaType.MANGA]
    return [MediaType.ANIME, MediaType.MANGA]


def _alias_conflicts_with_hints(match: AliasMatch, hints: TitleHints) -> bool:
    if hints.media_type is not None and match.media_type != hints.media_type:
        return True
    return False


def _alias_metadata_conflicts(media: ResolvedMedia, hints: TitleHints) -> bool:
    if hints.release_year is not None and media.release_year is not None:
        if media.release_year != hints.release_year:
            return True
    if hints.media_format and media.media_format:
        if media.media_format.lower() != hints.media_format.lower():
            return True
    return False
