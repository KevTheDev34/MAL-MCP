#!/usr/bin/env python3
"""Reversible MAL list update against a connected local account.

Development-only diagnostic. Requires a prior OAuth connect. Never deletes
entries. Does not print tokens or Authorization headers.

Example:

    python scripts/mal_reversible_list_update.py \\
        --media anime --mal-id 9253 --field score --value 8
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as ``python scripts/...`` from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.auth.service import MalOAuthService
from backend.app.config import Settings, get_settings
from backend.app.mal.client import MalClient
from backend.app.mal.errors import MalError
from backend.app.mal.models import (
    AnimeListEntry,
    AnimeListUpdate,
    MangaListEntry,
    MangaListUpdate,
)
from backend.app.services.clock import SystemClock
from backend.app.services.encryption import EncryptionService

ListEntry = AnimeListEntry | MangaListEntry
ListUpdate = AnimeListUpdate | MangaListUpdate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read a MAL list entry, apply a small reversible update, verify, "
            "restore, and verify again. Interactive confirmation required."
        )
    )
    parser.add_argument("--media", choices=("anime", "manga"), required=True)
    parser.add_argument("--mal-id", type=int, required=True)
    parser.add_argument(
        "--field",
        choices=(
            "score",
            "num_watched_episodes",
            "num_chapters_read",
            "num_volumes_read",
        ),
        required=True,
    )
    parser.add_argument("--value", type=int, required=True)
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Allow running when APP_ENV=production (still requires confirmation).",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if args.field == "score" and not (0 <= args.value <= 10):
        raise SystemExit("--value for score must be between 0 and 10")
    if args.media == "anime" and args.field in {
        "num_chapters_read",
        "num_volumes_read",
    }:
        raise SystemExit(f"--field {args.field} is not valid for anime")
    if args.media == "manga" and args.field == "num_watched_episodes":
        raise SystemExit("--field num_watched_episodes is not valid for manga")


def _read_status_value(entry: ListEntry, field: str) -> int:
    status = entry.list_status
    if field == "score":
        return int(status.score)
    if field == "num_watched_episodes":
        assert isinstance(entry, AnimeListEntry)
        return int(entry.list_status.num_episodes_watched)
    if field == "num_chapters_read":
        assert isinstance(entry, MangaListEntry)
        return int(entry.list_status.num_chapters_read)
    if field == "num_volumes_read":
        assert isinstance(entry, MangaListEntry)
        return int(entry.list_status.num_volumes_read)
    raise SystemExit(f"Unsupported field: {field}")


def _build_update(media: str, field: str, value: int) -> ListUpdate:
    if media == "anime":
        return AnimeListUpdate.model_validate({field: value})
    return MangaListUpdate.model_validate({field: value})


def _print_entry(media: str, mal_id: int, entry: ListEntry | None) -> None:
    if entry is None:
        print(f"{media} {mal_id}: not on list")
        return
    if isinstance(entry, AnimeListEntry):
        status = entry.list_status
        print(
            f"{media} {mal_id}: status={status.status} score={status.score} "
            f"episodes={status.num_episodes_watched}"
        )
        return
    status = entry.list_status
    print(
        f"{media} {mal_id}: status={status.status} score={status.score} "
        f"chapters={status.num_chapters_read} volumes={status.num_volumes_read}"
    )


async def _run(settings: Settings, args: argparse.Namespace) -> int:
    engine = create_engine(settings.database_url, future=True)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session: Session = SessionLocal()
    oauth = MalOAuthService(
        session=session,
        settings=settings,
        encryption=EncryptionService(settings.token_encryption_key),
        clock=SystemClock(),
    )
    client = MalClient(settings=settings, token_provider=oauth)
    try:
        if args.media == "anime":
            before = await client.get_anime_list_entry(args.mal_id)
        else:
            before = await client.get_manga_list_entry(args.mal_id)

        print("Current remote state:")
        _print_entry(args.media, args.mal_id, before)
        if before is None:
            print("Entry is not on the list; refusing to create via this script.")
            return 1

        original = _read_status_value(before, args.field)
        if original == args.value:
            print("Requested value already matches remote; nothing to do.")
            return 0

        print(
            f"Proposed change: {args.field} {original} -> {args.value} "
            f"on {args.media} id={args.mal_id}"
        )
        confirm = input("Type 'yes' to apply (will restore afterward): ").strip()
        if confirm != "yes":
            print("Aborted.")
            return 1

        update = _build_update(args.media, args.field, args.value)
        if args.media == "anime":
            assert isinstance(update, AnimeListUpdate)
            await client.update_anime_list_entry(args.mal_id, update)
            mid = await client.get_anime_list_entry(args.mal_id)
        else:
            assert isinstance(update, MangaListUpdate)
            await client.update_manga_list_entry(args.mal_id, update)
            mid = await client.get_manga_list_entry(args.mal_id)

        print("After update:")
        _print_entry(args.media, args.mal_id, mid)
        if mid is None or _read_status_value(mid, args.field) != args.value:
            print("ERROR: update verification failed")
            return 2

        restore = _build_update(args.media, args.field, original)
        if args.media == "anime":
            assert isinstance(restore, AnimeListUpdate)
            await client.update_anime_list_entry(args.mal_id, restore)
            after = await client.get_anime_list_entry(args.mal_id)
        else:
            assert isinstance(restore, MangaListUpdate)
            await client.update_manga_list_entry(args.mal_id, restore)
            after = await client.get_manga_list_entry(args.mal_id)

        print("After restore:")
        _print_entry(args.media, args.mal_id, after)
        if after is None or _read_status_value(after, args.field) != original:
            print("ERROR: restore verification failed")
            return 3

        print("OK: update verified and original state restored.")
        return 0
    except MalError as exc:
        print(f"MAL error ({exc.error_code}): {exc.message}")
        return 4
    finally:
        await client.aclose()
        await oauth.aclose()
        session.close()
        engine.dispose()


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    args = _parse_args()
    _validate_args(args)

    if settings.app_env == "production" and not args.i_know_what_im_doing:
        raise SystemExit(
            "Refusing to run when APP_ENV=production without "
            "--i-know-what-im-doing"
        )

    try:
        settings.require_mal_oauth_settings()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    raise SystemExit(asyncio.run(_run(settings, args)))


if __name__ == "__main__":
    main()
