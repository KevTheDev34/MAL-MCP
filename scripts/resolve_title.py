#!/usr/bin/env python3
"""Read-only title resolution diagnostic against a connected MAL account.

Never updates MAL. Never prints tokens or Authorization headers.

Examples:

    python scripts/resolve_title.py "Steins;Gate"
    python scripts/resolve_title.py "Pluto" --media manga
    python scripts/resolve_title.py "Vinland Saga season 2"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.auth.service import MalOAuthService
from backend.app.config import Settings, get_settings
from backend.app.db.repositories.title_aliases import TitleAliasRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.domain.enums import MediaType
from backend.app.mal.client import MalClient
from backend.app.mal.errors import MalError
from backend.app.resolver.aliases import AliasService
from backend.app.resolver.errors import ResolverError
from backend.app.resolver.hints import extract_title_hints
from backend.app.resolver.models import (
    AmbiguousOutcome,
    NotFoundOutcome,
    ResolveTitleRequest,
    ResolvedOutcome,
)
from backend.app.resolver.normalize import (
    normalize_for_comparison,
    normalize_for_search,
)
from backend.app.resolver.policy import ResolverPolicy
from backend.app.resolver.service import TitleResolver
from backend.app.services.clock import SystemClock
from backend.app.services.encryption import EncryptionService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve a title against MAL (read-only diagnostic)."
    )
    parser.add_argument("title", help="Title phrase to resolve")
    parser.add_argument(
        "--media",
        choices=("anime", "manga"),
        default=None,
        help="Optional media-type hint",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Optional release-year hint",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Optional season-number hint",
    )
    parser.add_argument(
        "--format",
        dest="media_format",
        default=None,
        help="Optional media format hint (tv, movie, manga, ...)",
    )
    parser.add_argument(
        "--no-aliases",
        action="store_true",
        help="Disable user alias lookup",
    )
    return parser.parse_args()


def _format_candidate_line(
    media_title: str,
    media_format: str | None,
    year: int | None,
    totals: str,
) -> str:
    parts = [media_title]
    if media_format:
        parts.append(media_format)
    if year is not None:
        parts.append(str(year))
    if totals:
        parts.append(totals)
    return " — ".join(parts)


def _totals_label(
    *,
    episodes: int | None,
    chapters: int | None,
    volumes: int | None,
) -> str:
    if episodes is not None:
        return f"{episodes} episodes"
    bits: list[str] = []
    if chapters is not None:
        bits.append(f"{chapters} chapters")
    if volumes is not None:
        bits.append(f"{volumes} volumes")
    return ", ".join(bits)


async def _resolve(settings: Settings, args: argparse.Namespace) -> int:
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session: Session = SessionLocal()
    clock = SystemClock()
    oauth: MalOAuthService | None = None
    client: MalClient | None = None
    try:
        encryption = EncryptionService(settings.token_encryption_key)
        oauth = MalOAuthService(
            session=session,
            settings=settings,
            encryption=encryption,
            clock=clock,
        )
        client = MalClient(settings=settings, token_provider=oauth)
        user = UserRepository(session).get_or_create_local_user()
        session.commit()

        policy = ResolverPolicy(
            search_limit=settings.resolver_search_limit,
            max_enrich_candidates=settings.resolver_max_enrich_candidates,
            max_ambiguity_candidates=settings.resolver_max_ambiguity_candidates,
            max_mal_gets=settings.resolver_max_mal_gets,
            resolve_min_confidence=settings.resolver_resolve_min_confidence,
            resolve_min_margin=settings.resolver_resolve_min_margin,
            resolve_min_raw_score=settings.resolver_resolve_min_raw_score,
            plausible_min_raw_score=settings.resolver_plausible_min_raw_score,
        )
        resolver = TitleResolver(
            mal_client=client,
            alias_service=AliasService(
                repository=TitleAliasRepository(session),
                clock=clock,
            ),
            policy=policy,
        )

        media_type = MediaType(args.media) if args.media else None
        request = ResolveTitleRequest(
            title=args.title,
            media_type=media_type,
            release_year=args.year,
            season_number=args.season,
            media_format=args.media_format,
            allow_aliases=not args.no_aliases,
        )
        hints = extract_title_hints(request.title)

        print(f"query: {request.title}")
        print(f"normalized_search: {normalize_for_search(request.title)}")
        print(f"normalized_comparison: {normalize_for_comparison(request.title)}")
        print(f"extracted_hints: {hints.model_dump()}")
        print()

        outcome = await resolver.resolve(user_id=user.id, request=request)
        session.commit()

        if isinstance(outcome, ResolvedOutcome):
            media = outcome.media
            print(
                "outcome: resolved "
                f"(candidates_considered={outcome.candidates_considered})"
            )
            print(
                "match: "
                + _format_candidate_line(
                    media.canonical_title,
                    media.media_format,
                    media.release_year,
                    _totals_label(
                        episodes=media.total_episodes,
                        chapters=media.total_chapters,
                        volumes=media.total_volumes,
                    ),
                )
            )
            print(f"mal_id: {media.mal_id} ({media.media_type.value})")
            print(f"confidence: {media.confidence}")
            print(f"reasons: {media.confidence_reasons}")
            return 0

        if isinstance(outcome, AmbiguousOutcome):
            print(f"outcome: ambiguous — {outcome.reason}")
            for candidate in outcome.candidates:
                media = candidate.media
                line = _format_candidate_line(
                    media.canonical_title,
                    media.media_format,
                    media.release_year,
                    _totals_label(
                        episodes=media.total_episodes,
                        chapters=media.total_chapters,
                        volumes=media.total_volumes,
                    ),
                )
                print(
                    f"  #{candidate.rank} {line} "
                    f"[score={candidate.raw_score} conf={candidate.confidence}]"
                )
                print(f"     + {candidate.positive_reasons}")
                print(f"     - {candidate.penalties}")
            return 0

        if isinstance(outcome, NotFoundOutcome):
            print(f"outcome: not_found — {outcome.reason}")
            return 0

        print(f"outcome: unexpected {outcome!r}")
        return 1
    except (ResolverError, MalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if client is not None:
            await client.aclose()
        if oauth is not None:
            await oauth.aclose()
        session.close()
        engine.dispose()


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    settings.require_mal_oauth_settings()
    raise SystemExit(asyncio.run(_resolve(settings, args)))


if __name__ == "__main__":
    main()
