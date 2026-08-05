#!/usr/bin/env python3
"""Show durable command history (Phase 7). Never prints tokens."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.commands.history import HistoryService
from backend.app.config import get_settings
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.db.repositories.users import UserRepository


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show command audit history.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--command-id", default=None)
    parser.add_argument("--state", default=None)
    parser.add_argument("--is-undo", action="store_true", default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        user = UserRepository(session).get_or_create_local_user()
        session.commit()
        history = HistoryService(repository=CommandPlanRepository(session))
        if args.command_id:
            detail = history.get_command_history(
                user_id=user.id,
                command_id=UUID(args.command_id),
            )
            print(json.dumps(detail.model_dump(mode="json"), indent=2, default=str))
            return 0
        listing = history.list_history(
            user_id=user.id,
            limit=args.limit,
            offset=args.offset,
            state=args.state,
            is_undo=True if args.is_undo else None,
        )
        print(f"total={listing.total} limit={listing.limit} offset={listing.offset}")
        for item in listing.items:
            print(
                f"{item.created_at.isoformat()} "
                f"command={item.command_id} state={item.state.value} "
                f"plan={item.plan_id} undo={item.is_undo} "
                f"items={item.item_count} verified={item.verified_count}"
            )
        return 0
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
