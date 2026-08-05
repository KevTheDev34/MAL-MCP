#!/usr/bin/env python3
"""Recover interrupted application attempts without blind MAL rewrites."""

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
from backend.app.commands.recovery import ApplicationRecoveryService
from backend.app.config import get_settings
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.mal.client import MalClient
from backend.app.services.clock import SystemClock
from backend.app.services.encryption import EncryptionService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover interrupted plan application."
    )
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--revision", type=int, required=True)
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
        recovery = ApplicationRecoveryService(
            repository=CommandPlanRepository(session),
            mal_client=client,
            clock=clock,
            apply_claim_stale_seconds=settings.apply_claim_stale_seconds,
        )
        result = await recovery.recover_plan(
            user_id=user.id,
            plan_id=UUID(args.plan_id),
            revision=args.revision,
        )
        print(f"plan_id={result.plan_id} revision={result.revision}")
        print(f"state={result.state.value} next_action={result.next_action}")
        for item in result.items:
            print(
                f"  item={item.item_id} classification={item.classification} "
                f"result={item.apply_result.value} wrote_again={item.wrote_again}"
            )
            if item.message:
                print(f"    message={item.message}")
            if item.observed_state:
                print(f"    observed={item.observed_state.model_dump(mode='json')}")
        print(json.dumps(result.model_dump(mode="json"), default=str, indent=2))
        return 0
    finally:
        if client is not None:
            await client.aclose()
        if oauth is not None:
            await oauth.aclose()
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
