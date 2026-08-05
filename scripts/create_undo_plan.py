#!/usr/bin/env python3
"""Create a reverse undo plan through Phase 7 UndoService. Does not apply."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.auth.service import MalOAuthService
from backend.app.commands.models import CreateUndoPlanRequest
from backend.app.commands.undo import UndoService
from backend.app.config import get_settings
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.domain.enums import CommandSourceType
from backend.app.mal.client import MalClient
from backend.app.services.clock import SystemClock
from backend.app.services.encryption import EncryptionService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a stored reverse undo plan.")
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--item-id", default=None)
    parser.add_argument("--reason", default=None)
    return parser.parse_args()


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
        undo = UndoService(
            repository=CommandPlanRepository(session),
            mal_client=client,
            clock=clock,
            plan_expiration_minutes=settings.plan_expiration_minutes,
            source_type=CommandSourceType.DIAGNOSTIC,
        )
        item_ids = [UUID(args.item_id)] if args.item_id else None
        result = await undo.create_undo_plan_for_command(
            user_id=user.id,
            command_id=UUID(args.command_id),
            request=CreateUndoPlanRequest(item_ids=item_ids, reason=args.reason),
        )
        print(f"original_command_id={result.original_command_id}")
        print(f"reverse_command_id={result.reverse_command_id}")
        print(f"reverse_plan_id={result.reverse_plan.plan_id}")
        print(f"plan_hash={result.reverse_plan.plan_hash}")
        print(
            f"ready={result.ready_count} conflict={result.conflict_count} "
            f"skipped={result.skipped_count}"
        )
        for item in result.items:
            print(
                f"  item={item.original_item_id} outcome={item.outcome.value} "
                f"reason={item.reason}"
            )
            if item.planned_before:
                print(
                    "    planned_before="
                    f"{item.planned_before.model_dump(mode='json')}"
                )
            if item.verified_after:
                print(
                    "    verified_after="
                    f"{item.verified_after.model_dump(mode='json')}"
                )
            if item.undo_check_observed:
                print(
                    "    undo_check_observed="
                    f"{item.undo_check_observed.model_dump(mode='json')}"
                )
            if item.proposed_restore:
                print(
                    "    proposed_restore="
                    f"{item.proposed_restore.model_dump(mode='json')}"
                )
            if item.conflict_fields:
                print(f"    conflict_fields={item.conflict_fields}")
        print("Confirm and apply the reverse plan with the normal Phase 6 flow.")
        print(
            json.dumps(
                {
                    "reverse_plan_id": str(result.reverse_plan.plan_id),
                    "revision": result.reverse_plan.revision,
                    "plan_hash": result.reverse_plan.plan_hash,
                }
            )
        )
        return 0 if result.ready_count else 1
    finally:
        if client is not None:
            await client.aclose()
        if oauth is not None:
            await oauth.aclose()
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
