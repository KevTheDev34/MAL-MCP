#!/usr/bin/env python3
"""Plan / confirm / apply a MAL list change through the Phase 6 command service.

Never bypasses the command application service. Never prints tokens.

Examples:

    python scripts/plan_mal_change.py \
      --media anime --title "Steins;Gate" --score 8
    python scripts/plan_mal_change.py \
      --media anime --title "Steins;Gate" --score 8 --plan-only
    python scripts/plan_mal_change.py \
      --media manga --title "Pluto" --status completed --plan-only
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
from sqlalchemy.orm import sessionmaker

from backend.app.auth.service import MalOAuthService
from backend.app.commands.confirmation import PlanConfirmationService
from backend.app.commands.executor import ChangePlanExecutor
from backend.app.commands.history import HistoryService
from backend.app.commands.models import CreateChangePlanRequest
from backend.app.commands.planner import ChangePlanner
from backend.app.commands.recovery import ApplicationRecoveryService
from backend.app.commands.service import CommandApplicationService
from backend.app.commands.undo import UndoService
from backend.app.config import get_settings
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.db.repositories.title_aliases import TitleAliasRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.domain.enums import (
    AnimeStatus,
    CommandSourceType,
    MangaStatus,
    MediaType,
)
from backend.app.domain.requests import RequestedChange
from backend.app.mal.client import MalClient
from backend.app.resolver.aliases import AliasService
from backend.app.resolver.policy import ResolverPolicy
from backend.app.resolver.service import TitleResolver
from backend.app.services.clock import SystemClock
from backend.app.services.encryption import EncryptionService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan (and optionally confirm/apply) a MAL list change."
    )
    parser.add_argument("--media", choices=("anime", "manga"), required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--status",
        default=None,
        help="List status (watching/completed/..., or reading/plan_to_read/...)",
    )
    parser.add_argument("--score", type=int, default=None)
    parser.add_argument("--episodes", type=int, default=None)
    parser.add_argument("--chapters", type=int, default=None)
    parser.add_argument("--volumes", type=int, default=None)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Create and display the plan without confirm/apply prompts",
    )
    return parser.parse_args()


def _build_requested(args: argparse.Namespace) -> RequestedChange:
    media = MediaType(args.media)
    status = None
    if args.status:
        if media is MediaType.ANIME:
            status = AnimeStatus(args.status)
        else:
            status = MangaStatus(args.status)
    return RequestedChange(
        title=args.title,
        media_type=media,
        status=status,
        score=args.score,
        episode_progress=args.episodes if media is MediaType.ANIME else None,
        chapter_progress=args.chapters if media is MediaType.MANGA else None,
        volume_progress=args.volumes if media is MediaType.MANGA else None,
    )


def _print_plan(plan: object) -> None:
    from backend.app.commands.models import ChangePlanView

    assert isinstance(plan, ChangePlanView)
    print(f"plan_id={plan.plan_id}")
    print(f"revision={plan.revision}")
    print(f"state={plan.state.value}")
    print(f"plan_hash={plan.plan_hash}")
    print(f"expires_at={plan.expires_at.isoformat()}")
    print(f"confirmable={plan.confirmable}")
    print("--- items ---")
    for item in plan.items:
        print(f"[{item.apply_order}] kind={item.kind}")
        print(f"  requested title={item.requested.title!r}")
        if hasattr(item, "media") and item.media is not None:
            print(
                f"  media={item.media.media_type.value} "
                f"mal_id={item.media.mal_id} title={item.media.canonical_title!r}"
            )
        if hasattr(item, "before") and item.before is not None:
            print(f"  before={item.before.model_dump(mode='json')}")
        if hasattr(item, "after") and item.after is not None:
            print(f"  after={item.after.model_dump(mode='json')}")
        if hasattr(item, "warnings") and item.warnings:
            for warning in item.warnings:
                print(f"  warning[{warning.code.value}] {warning.message}")
        if hasattr(item, "candidates"):
            for cand in item.candidates:
                print(
                    f"  candidate rank={cand.rank} "
                    f"mal_id={cand.media.mal_id} "
                    f"title={cand.media.canonical_title!r} "
                    f"year={cand.media.release_year}"
                )
        if hasattr(item, "error_message"):
            print(f"  error={item.error_code}: {item.error_message}")
        if hasattr(item, "reason"):
            print(f"  reason={item.reason}")


async def _main() -> int:
    args = _parse_args()
    settings = get_settings()
    settings.require_mal_oauth_settings()

    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    clock = SystemClock()
    oauth: MalOAuthService | None = None
    client: MalClient | None = None
    exit_code = 1

    try:
        user = UserRepository(session).get_or_create_local_user()
        session.commit()

        encryption = EncryptionService(settings.token_encryption_key)
        oauth = MalOAuthService(
            session=session,
            settings=settings,
            encryption=encryption,
            clock=clock,
        )
        client = MalClient(settings=settings, token_provider=oauth)
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
        repo = CommandPlanRepository(session)
        undo = UndoService(
            repository=repo,
            mal_client=client,
            clock=clock,
            plan_expiration_minutes=settings.plan_expiration_minutes,
            source_type=CommandSourceType.DIAGNOSTIC,
        )
        service = CommandApplicationService(
            planner=ChangePlanner(
                repository=repo,
                resolver=resolver,
                mal_client=client,
                clock=clock,
                plan_expiration_minutes=settings.plan_expiration_minutes,
                max_plan_changes=settings.max_plan_changes,
            ),
            confirmation=PlanConfirmationService(repository=repo, clock=clock),
            executor=ChangePlanExecutor(
                repository=repo,
                mal_client=client,
                clock=clock,
                apply_claim_stale_seconds=settings.apply_claim_stale_seconds,
                undo_service=undo,
            ),
            repository=repo,
            clock=clock,
            recovery=ApplicationRecoveryService(
                repository=repo,
                mal_client=client,
                clock=clock,
                apply_claim_stale_seconds=settings.apply_claim_stale_seconds,
            ),
            undo=undo,
            history=HistoryService(repository=repo),
            source_type=CommandSourceType.DIAGNOSTIC,
        )

        requested = _build_requested(args)
        plan = await service.create_plan(
            user_id=user.id,
            request=CreateChangePlanRequest(changes=[requested]),
        )
        _print_plan(plan)

        if args.plan_only:
            print("plan-only mode: no confirm/apply")
            exit_code = 0
            return exit_code

        if not plan.confirmable:
            print("Plan is not confirmable (no ready applyable changes).")
            return exit_code

        answer = input("Confirm this stored plan? [yes/no]: ").strip().lower()
        if answer != "yes":
            print("Confirmation declined.")
            return exit_code

        confirmed = service.confirm(
            user_id=user.id,
            plan_id=plan.plan_id,
            revision=plan.revision,
            plan_hash=plan.plan_hash,
        )
        print(
            f"confirmed_at={confirmed.confirmed_at.isoformat()} "
            f"applyable={confirmed.applyable}"
        )

        answer = input("Apply the confirmed plan to MAL? [yes/no]: ").strip().lower()
        if answer != "yes":
            print("Apply declined; plan remains confirmed until expiry/cancel.")
            exit_code = 0
            return exit_code

        result = await service.apply(
            user_id=user.id,
            plan_id=plan.plan_id,
            revision=plan.revision,
        )
        print(
            f"apply state={result.state.value} "
            f"already_applied={result.already_applied}"
        )
        for item in result.results:
            print(
                f"  [{item.apply_order}] {item.result.value} "
                f"mal_id={item.mal_id} title={item.canonical_title!r}"
            )
            if item.verified_state is not None:
                print(f"    verified={item.verified_state.model_dump(mode='json')}")
            if item.error_message:
                print(f"    error={item.error_code}: {item.error_message}")
        exit_code = (
            0 if result.state.value in {"verified", "partially_applied"} else 1
        )
        return exit_code
    finally:
        if client is not None:
            await client.aclose()
        if oauth is not None:
            await oauth.aclose()
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
