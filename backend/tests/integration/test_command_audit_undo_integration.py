"""Integration tests for Phase 7 audit, history, recovery, and undo."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.commands.confirmation import PlanConfirmationService
from backend.app.commands.errors import UndoNotEligibleError
from backend.app.commands.executor import ChangePlanExecutor
from backend.app.commands.history import HistoryService
from backend.app.commands.models import CreateChangePlanRequest, CreateUndoPlanRequest
from backend.app.commands.planner import ChangePlanner
from backend.app.commands.recovery import ApplicationRecoveryService
from backend.app.commands.service import CommandApplicationService
from backend.app.commands.undo import UndoService
from backend.app.db.base import Base
from backend.app.db.models import ApplicationAttempt
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.domain.enums import (
    AnimeStatus,
    ApplicationAttemptState,
    ApplyResultKind,
    CommandState,
    MediaType,
    OutcomeCertainty,
    UndoItemOutcomeKind,
)
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.requests import RequestedChange
from backend.app.mal.models import AnimeListEntry, AnimeListStatus
from backend.app.resolver.models import ResolvedOutcome
from backend.app.services.clock import FixedClock


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 8, 4, 18, 0, 0, tzinfo=UTC))


@pytest.fixture
def user_id(db_session: Session) -> str:
    user = UserRepository(db_session).get_or_create_local_user()
    db_session.commit()
    return user.id


def _steins_media() -> ResolvedMedia:
    return ResolvedMedia(
        mal_id=9253,
        media_type=MediaType.ANIME,
        canonical_title="Steins;Gate",
        total_episodes=24,
        confidence=0.99,
        publication_status="finished_airing",
    )


def _anime_entry(
    *,
    status: str = "watching",
    score: int = 0,
    episodes: int = 10,
) -> AnimeListEntry:
    return AnimeListEntry(
        mal_id=9253,
        title="Steins;Gate",
        list_status=AnimeListStatus(
            status=status,
            score=score,
            num_episodes_watched=episodes,
            is_rewatching=False,
        ),
    )


def _build_service(
    *,
    db_session: Session,
    clock: FixedClock,
    resolver: Any,
    mal: Any,
) -> CommandApplicationService:
    repo = CommandPlanRepository(db_session)
    undo = UndoService(
        repository=repo,
        mal_client=mal,
        clock=clock,
        plan_expiration_minutes=30,
    )
    return CommandApplicationService(
        planner=ChangePlanner(
            repository=repo,
            resolver=resolver,
            mal_client=mal,
            clock=clock,
            plan_expiration_minutes=30,
            max_plan_changes=25,
        ),
        confirmation=PlanConfirmationService(repository=repo, clock=clock),
        executor=ChangePlanExecutor(
            repository=repo,
            mal_client=mal,
            clock=clock,
            undo_service=undo,
        ),
        repository=repo,
        clock=clock,
        recovery=ApplicationRecoveryService(
            repository=repo,
            mal_client=mal,
            clock=clock,
        ),
        undo=undo,
        history=HistoryService(repository=repo),
    )


async def _plan_confirm_apply_score(
    service: CommandApplicationService,
    *,
    user_id: str,
    score: int = 8,
) -> Any:
    plan = await service.create_plan(
        user_id=user_id,
        request=CreateChangePlanRequest(
            changes=[
                RequestedChange(
                    title="Steins;Gate",
                    media_type=MediaType.ANIME,
                    score=score,
                )
            ]
        ),
    )
    service.confirm(
        user_id=user_id,
        plan_id=plan.plan_id,
        revision=plan.revision,
        plan_hash=plan.plan_hash,
    )
    return await service.apply(
        user_id=user_id,
        plan_id=plan.plan_id,
        revision=plan.revision,
    )


def test_history_and_undo_round_trip(
    db_session: Session,
    clock: FixedClock,
    user_id: str,
) -> None:
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(
        return_value=ResolvedOutcome(media=_steins_media(), candidates_considered=1)
    )
    mal = AsyncMock()
    # plan read, apply re-read, verify read, undo check, undo apply re-read, undo verify
    mal.get_anime_list_entry = AsyncMock(
        side_effect=[
            _anime_entry(score=7, episodes=10),
            _anime_entry(score=7, episodes=10),
            _anime_entry(score=8, episodes=10),
            _anime_entry(score=8, episodes=11),  # unrelated progress drift
            _anime_entry(score=8, episodes=11),
            _anime_entry(score=7, episodes=11),
        ]
    )
    mal.update_anime_list_entry = AsyncMock(return_value=None)
    service = _build_service(
        db_session=db_session, clock=clock, resolver=resolver, mal=mal
    )

    apply_result = asyncio.run(
        _plan_confirm_apply_score(service, user_id=user_id, score=8)
    )
    assert apply_result.state is CommandState.VERIFIED

    history = service.list_history(user_id=user_id, limit=10)
    assert history.total >= 1
    command_id = history.items[0].command_id
    detail = service.get_command_history(user_id=user_id, command_id=command_id)
    assert detail.items[0].planned_before is not None
    assert detail.items[0].proposed_after is not None
    assert detail.items[0].attempts
    assert "access_token" not in (detail.items[0].attempts[0].request or {})

    undo = asyncio.run(
        service.create_undo_plan(
            user_id=user_id,
            command_id=command_id,
            request=CreateUndoPlanRequest(),
        )
    )
    assert undo.ready_count == 1
    assert undo.items[0].outcome is UndoItemOutcomeKind.READY
    assert undo.items[0].proposed_restore is not None
    assert undo.items[0].proposed_restore.score == 7
    assert undo.items[0].proposed_restore.episode_progress == 11

    service.confirm(
        user_id=user_id,
        plan_id=undo.reverse_plan.plan_id,
        revision=undo.reverse_plan.revision,
        plan_hash=undo.reverse_plan.plan_hash,
    )
    reverse_apply = asyncio.run(
        service.apply(
            user_id=user_id,
            plan_id=undo.reverse_plan.plan_id,
            revision=undo.reverse_plan.revision,
        )
    )
    assert reverse_apply.state is CommandState.VERIFIED

    original = service.get_command_history(user_id=user_id, command_id=command_id)
    assert original.items[0].planned_before is not None
    assert original.items[0].planned_before.score == 7
    assert any(r.state.value == "verified" for r in original.reversions)


def test_same_field_conflict_blocks_undo(
    db_session: Session,
    clock: FixedClock,
    user_id: str,
) -> None:
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(
        return_value=ResolvedOutcome(media=_steins_media(), candidates_considered=1)
    )
    mal = AsyncMock()
    mal.get_anime_list_entry = AsyncMock(
        side_effect=[
            _anime_entry(score=7, episodes=10),
            _anime_entry(score=7, episodes=10),
            _anime_entry(score=8, episodes=10),
            _anime_entry(score=9, episodes=10),  # external same-field change
        ]
    )
    mal.update_anime_list_entry = AsyncMock(return_value=None)
    service = _build_service(
        db_session=db_session, clock=clock, resolver=resolver, mal=mal
    )
    asyncio.run(_plan_confirm_apply_score(service, user_id=user_id, score=8))
    command_id = service.list_history(user_id=user_id).items[0].command_id
    with pytest.raises(UndoNotEligibleError):
        asyncio.run(service.create_undo_plan(user_id=user_id, command_id=command_id))
    assert mal.update_anime_list_entry.await_count == 1


def test_recovery_intended_state_without_rewrite(
    db_session: Session,
    clock: FixedClock,
    user_id: str,
) -> None:
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(
        return_value=ResolvedOutcome(media=_steins_media(), candidates_considered=1)
    )
    mal = AsyncMock()
    mal.get_anime_list_entry = AsyncMock(
        side_effect=[
            _anime_entry(score=7, episodes=10),  # plan
            _anime_entry(score=8, episodes=10),  # recovery read
        ]
    )
    mal.update_anime_list_entry = AsyncMock(return_value=None)
    service = _build_service(
        db_session=db_session, clock=clock, resolver=resolver, mal=mal
    )
    plan = asyncio.run(
        service.create_plan(
            user_id=user_id,
            request=CreateChangePlanRequest(
                changes=[
                    RequestedChange(
                        title="Steins;Gate",
                        media_type=MediaType.ANIME,
                        score=8,
                    )
                ]
            ),
        )
    )
    service.confirm(
        user_id=user_id,
        plan_id=plan.plan_id,
        revision=plan.revision,
        plan_hash=plan.plan_hash,
    )
    # Force an interrupted written_unverified attempt.
    repo = CommandPlanRepository(db_session)
    stored = repo.get_plan(plan.plan_id)
    assert stored is not None
    item = repo.list_items(stored.id)[0]
    from backend.app.commands.idempotency import build_apply_idempotency_key

    key = build_apply_idempotency_key(
        user_id=user_id,
        plan_id=stored.id,
        revision=stored.revision,
        planned_item_id=item.id,
        plan_hash=stored.plan_hash,
    )
    attempt = ApplicationAttempt(
        planned_item_id=item.id,
        attempt_number=1,
        state=ApplicationAttemptState.WRITTEN_UNVERIFIED.value,
        idempotency_key=key,
        outcome_certainty=OutcomeCertainty.UNCERTAIN.value,
        started_at=clock.now(),
    )
    db_session.add(attempt)
    stored.state = CommandState.APPLYING.value
    stored.apply_started_at = clock.now()
    item.apply_result_kind = ApplyResultKind.VERIFICATION_UNKNOWN.value
    db_session.commit()

    recovery = asyncio.run(
        service.recover(
            user_id=user_id,
            plan_id=plan.plan_id,
            revision=plan.revision,
        )
    )
    assert recovery.items[0].classification == "intended_state_present"
    assert recovery.items[0].wrote_again is False
    assert mal.update_anime_list_entry.await_count == 0


def test_not_on_list_not_reversible(
    db_session: Session,
    clock: FixedClock,
    user_id: str,
) -> None:
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(
        return_value=ResolvedOutcome(media=_steins_media(), candidates_considered=1)
    )
    mal = AsyncMock()
    mal.get_anime_list_entry = AsyncMock(
        side_effect=[
            None,  # not on list at plan
            None,  # apply re-read
            _anime_entry(status="plan_to_watch", score=0, episodes=0),
        ]
    )
    mal.update_anime_list_entry = AsyncMock(return_value=None)
    service = _build_service(
        db_session=db_session, clock=clock, resolver=resolver, mal=mal
    )
    plan = asyncio.run(
        service.create_plan(
            user_id=user_id,
            request=CreateChangePlanRequest(
                changes=[
                    RequestedChange(
                        title="Steins;Gate",
                        media_type=MediaType.ANIME,
                        status=AnimeStatus.PLAN_TO_WATCH,
                    )
                ]
            ),
        )
    )
    service.confirm(
        user_id=user_id,
        plan_id=plan.plan_id,
        revision=plan.revision,
        plan_hash=plan.plan_hash,
    )
    applied = asyncio.run(
        service.apply(
            user_id=user_id,
            plan_id=plan.plan_id,
            revision=plan.revision,
        )
    )
    assert applied.state is CommandState.VERIFIED
    command_id = service.list_history(user_id=user_id).items[0].command_id
    with pytest.raises(UndoNotEligibleError):
        asyncio.run(service.create_undo_plan(user_id=user_id, command_id=command_id))
