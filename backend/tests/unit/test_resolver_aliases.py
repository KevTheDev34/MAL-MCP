"""Unit tests for alias repository and AliasService."""

from __future__ import annotations

from datetime import UTC, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.app.db.repositories.title_aliases import TitleAliasRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.domain.enums import MediaType
from backend.app.resolver.aliases import AliasService
from backend.app.resolver.normalize import normalize_for_comparison
from backend.app.services.clock import FixedClock


@pytest.fixture
def user_id(db_session: Session) -> str:
    return UserRepository(db_session).get_or_create_local_user().id


@pytest.fixture
def alias_service(db_session: Session, fixed_clock: FixedClock) -> AliasService:
    return AliasService(
        repository=TitleAliasRepository(db_session),
        clock=fixed_clock,
    )


def test_save_and_exact_lookup(
    alias_service: AliasService,
    user_id: str,
    db_session: Session,
) -> None:
    saved = alias_service.save(
        user_id=user_id,
        alias="FMA",
        media_type=MediaType.ANIME,
        mal_id=5114,
        canonical_title="Fullmetal Alchemist: Brotherhood",
    )
    db_session.commit()
    assert saved.alias_normalized == normalize_for_comparison("FMA")

    matches = alias_service.lookup(
        user_id=user_id,
        title="fma",
        media_type=MediaType.ANIME,
    )
    assert len(matches) == 1
    assert matches[0].mal_id == 5114


def test_media_specific_alias(
    alias_service: AliasService,
    user_id: str,
    db_session: Session,
) -> None:
    alias_service.save(
        user_id=user_id,
        alias="Pluto",
        media_type=MediaType.MANGA,
        mal_id=7675,
        canonical_title="Pluto",
    )
    alias_service.save(
        user_id=user_id,
        alias="Pluto",
        media_type=MediaType.ANIME,
        mal_id=53275,
        canonical_title="Pluto",
    )
    db_session.commit()

    manga = alias_service.lookup(
        user_id=user_id, title="Pluto", media_type=MediaType.MANGA
    )
    anime = alias_service.lookup(
        user_id=user_id, title="Pluto", media_type=MediaType.ANIME
    )
    assert manga[0].mal_id == 7675
    assert anime[0].mal_id == 53275


def test_alias_update_and_last_used(
    alias_service: AliasService,
    user_id: str,
    db_session: Session,
    fixed_clock: FixedClock,
) -> None:
    first = alias_service.save(
        user_id=user_id,
        alias="Bebop",
        media_type=MediaType.ANIME,
        mal_id=1,
        canonical_title="Cowboy Bebop",
    )
    db_session.commit()
    created = first.created_at
    first_used = first.last_used_at

    fixed_clock.set(first_used + timedelta(hours=2))
    updated = alias_service.save(
        user_id=user_id,
        alias="Bebop",
        media_type=MediaType.ANIME,
        mal_id=1,
        canonical_title="Cowboy Bebop",
    )
    db_session.commit()
    assert updated.created_at == created
    assert updated.last_used_at > first_used


def test_touch_updates_timestamp(
    alias_service: AliasService,
    user_id: str,
    db_session: Session,
    fixed_clock: FixedClock,
) -> None:
    saved = alias_service.save(
        user_id=user_id,
        alias="HxH 2011",
        media_type=MediaType.ANIME,
        mal_id=11061,
        canonical_title="Hunter x Hunter (2011)",
    )
    db_session.commit()
    before = saved.last_used_at
    fixed_clock.set(before + timedelta(minutes=30))
    alias_service.touch(saved)
    db_session.commit()
    assert saved.last_used_at.replace(tzinfo=UTC) == fixed_clock.now()
    assert saved.last_used_at.replace(tzinfo=UTC) > before.replace(tzinfo=UTC)


def test_duplicate_constraint_upserts(
    alias_service: AliasService,
    user_id: str,
    db_session: Session,
) -> None:
    alias_service.save(
        user_id=user_id,
        alias="FMA",
        media_type=MediaType.ANIME,
        mal_id=5114,
        canonical_title="Fullmetal Alchemist: Brotherhood",
    )
    alias_service.save(
        user_id=user_id,
        alias="FMA",
        media_type=MediaType.ANIME,
        mal_id=5114,
        canonical_title="Fullmetal Alchemist: Brotherhood",
    )
    db_session.commit()
    matches = alias_service.lookup(
        user_id=user_id, title="FMA", media_type=MediaType.ANIME
    )
    assert len(matches) == 1
