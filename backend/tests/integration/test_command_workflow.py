"""Integration tests for plan → confirm → apply → verify workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.commands.confirmation import PlanConfirmationService
from backend.app.commands.errors import (
    PlanExpiredError,
    PlanHashMismatchError,
    PlanNotConfirmableError,
    PlanOwnershipError,
)
from backend.app.commands.executor import ChangePlanExecutor
from backend.app.commands.models import CreateChangePlanRequest
from backend.app.commands.planner import ChangePlanner
from backend.app.commands.service import CommandApplicationService
from backend.app.db.base import Base
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.db.repositories.users import UserRepository
from backend.app.domain.enums import (
    AnimeStatus,
    ApplyResultKind,
    CommandState,
    MediaType,
    PlannedItemOutcomeKind,
)
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.requests import RequestedChange
from backend.app.mal.models import AnimeListEntry, AnimeListStatus, AnimeListUpdate
from backend.app.resolver.models import (
    AmbiguousOutcome,
    NotFoundOutcome,
    ResolutionCandidate,
    ResolvedOutcome,
)
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
    from backend.app.commands.history import HistoryService
    from backend.app.commands.recovery import ApplicationRecoveryService
    from backend.app.commands.undo import UndoService
    from backend.app.domain.enums import CommandSourceType

    repo = CommandPlanRepository(db_session)
    undo = UndoService(
        repository=repo,
        mal_client=mal,
        clock=clock,
        plan_expiration_minutes=30,
        source_type=CommandSourceType.API,
    )
    planner = ChangePlanner(
        repository=repo,
        resolver=resolver,
        mal_client=mal,
        clock=clock,
        plan_expiration_minutes=30,
        max_plan_changes=25,
    )
    confirmation = PlanConfirmationService(repository=repo, clock=clock)
    executor = ChangePlanExecutor(
        repository=repo,
        mal_client=mal,
        clock=clock,
        apply_claim_stale_seconds=120,
        undo_service=undo,
    )
    return CommandApplicationService(
        planner=planner,
        confirmation=confirmation,
        executor=executor,
        repository=repo,
        clock=clock,
        recovery=ApplicationRecoveryService(
            repository=repo,
            mal_client=mal,
            clock=clock,
            apply_claim_stale_seconds=120,
        ),
        undo=undo,
        history=HistoryService(repository=repo),
    )


def test_plan_confirm_apply_anime_success(
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
            _anime_entry(status="watching", score=0, episodes=10),
            _anime_entry(status="watching", score=0, episodes=10),
            _anime_entry(status="completed", score=9, episodes=24),
        ]
    )
    mal.update_anime_list_entry = AsyncMock(
        return_value=_anime_entry(status="completed", score=9, episodes=24)
    )
    service = _build_service(
        db_session=db_session,
        clock=clock,
        resolver=resolver,
        mal=mal,
    )

    async def _run() -> None:
        plan = await service.create_plan(
            user_id=user_id,
            request=CreateChangePlanRequest(
                changes=[
                    RequestedChange(
                        title="Steins;Gate",
                        media_type=MediaType.ANIME,
                        status=AnimeStatus.COMPLETED,
                        score=9,
                    )
                ]
            ),
        )
        assert plan.state is CommandState.AWAITING_CONFIRMATION
        assert len(plan.items) == 1
        assert plan.items[0].kind is PlannedItemOutcomeKind.READY
        assert plan.items[0].after.episode_progress == 24  # type: ignore[union-attr]

        confirmed = service.confirm(
            user_id=user_id,
            plan_id=plan.plan_id,
            revision=plan.revision,
            plan_hash=plan.plan_hash,
        )
        assert confirmed.applyable is True

        applied = await service.apply(
            user_id=user_id,
            plan_id=plan.plan_id,
            revision=plan.revision,
        )
        assert applied.state is CommandState.VERIFIED
        assert applied.results[0].result is ApplyResultKind.VERIFIED
        mal.update_anime_list_entry.assert_awaited_once()
        args = mal.update_anime_list_entry.await_args
        assert args.args[0] == 9253
        assert isinstance(args.args[1], AnimeListUpdate)

        again = await service.apply(
            user_id=user_id,
            plan_id=plan.plan_id,
            revision=plan.revision,
        )
        assert again.already_applied is True
        assert mal.update_anime_list_entry.await_count == 1

    asyncio.run(_run())


def test_ambiguous_item_not_applyable(
    db_session: Session,
    clock: FixedClock,
    user_id: str,
) -> None:
    media_a = _steins_media()
    media_b = ResolvedMedia(
        mal_id=11061,
        media_type=MediaType.ANIME,
        canonical_title="Hunter x Hunter (2011)",
        total_episodes=148,
        confidence=0.7,
    )
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(
        return_value=AmbiguousOutcome(
            query="Hunter x Hunter",
            candidates=[
                ResolutionCandidate(
                    media=media_a,
                    raw_score=40,
                    confidence=0.7,
                    rank=1,
                ),
                ResolutionCandidate(
                    media=media_b,
                    raw_score=38,
                    confidence=0.65,
                    rank=2,
                ),
            ],
            reason="multiple strong matches",
        )
    )
    mal = AsyncMock()
    service = _build_service(
        db_session=db_session,
        clock=clock,
        resolver=resolver,
        mal=mal,
    )

    async def _run() -> None:
        plan = await service.create_plan(
            user_id=user_id,
            request=CreateChangePlanRequest(
                changes=[
                    RequestedChange(
                        title="Hunter x Hunter",
                        media_type=MediaType.ANIME,
                        status=AnimeStatus.COMPLETED,
                    )
                ]
            ),
        )
        assert plan.state is CommandState.AWAITING_CLARIFICATION
        assert plan.items[0].kind is PlannedItemOutcomeKind.AMBIGUOUS
        with pytest.raises(PlanNotConfirmableError):
            service.confirm(
                user_id=user_id,
                plan_id=plan.plan_id,
                revision=1,
                plan_hash=plan.plan_hash,
            )
        mal.update_anime_list_entry.assert_not_called()

    asyncio.run(_run())


def test_noop_plan_not_confirmable(
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
        return_value=_anime_entry(status="completed", score=9, episodes=24)
    )
    service = _build_service(
        db_session=db_session,
        clock=clock,
        resolver=resolver,
        mal=mal,
    )

    async def _run() -> None:
        plan = await service.create_plan(
            user_id=user_id,
            request=CreateChangePlanRequest(
                changes=[
                    RequestedChange(
                        title="Steins;Gate",
                        media_type=MediaType.ANIME,
                        status=AnimeStatus.COMPLETED,
                        score=9,
                    )
                ]
            ),
        )
        assert plan.items[0].kind is PlannedItemOutcomeKind.NOOP
        assert plan.state is CommandState.PLANNED
        with pytest.raises(PlanNotConfirmableError):
            service.confirm(
                user_id=user_id,
                plan_id=plan.plan_id,
                revision=1,
                plan_hash=plan.plan_hash,
            )

    asyncio.run(_run())


def test_stale_conflict_skips_write(
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
            _anime_entry(status="watching", score=0, episodes=7),
            _anime_entry(status="watching", score=0, episodes=10),
        ]
    )
    mal.update_anime_list_entry = AsyncMock()
    service = _build_service(
        db_session=db_session,
        clock=clock,
        resolver=resolver,
        mal=mal,
    )

    async def _run() -> None:
        plan = await service.create_plan(
            user_id=user_id,
            request=CreateChangePlanRequest(
                changes=[
                    RequestedChange(
                        title="Steins;Gate",
                        media_type=MediaType.ANIME,
                        status=AnimeStatus.COMPLETED,
                    )
                ]
            ),
        )
        service.confirm(
            user_id=user_id,
            plan_id=plan.plan_id,
            revision=1,
            plan_hash=plan.plan_hash,
        )
        applied = await service.apply(
            user_id=user_id,
            plan_id=plan.plan_id,
            revision=1,
        )
        assert applied.results[0].result is ApplyResultKind.STALE_CONFLICT
        mal.update_anime_list_entry.assert_not_called()
        assert applied.state is CommandState.FAILED

    asyncio.run(_run())


def test_wrong_hash_and_ownership(
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
        return_value=_anime_entry(status="watching", score=0, episodes=1)
    )
    service = _build_service(
        db_session=db_session,
        clock=clock,
        resolver=resolver,
        mal=mal,
    )

    async def _run() -> None:
        plan = await service.create_plan(
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
        with pytest.raises(PlanHashMismatchError):
            service.confirm(
                user_id=user_id,
                plan_id=plan.plan_id,
                revision=1,
                plan_hash="0" * 64,
            )
        with pytest.raises(PlanOwnershipError):
            service.confirm(
                user_id=str(uuid4()),
                plan_id=plan.plan_id,
                revision=1,
                plan_hash=plan.plan_hash,
            )

    asyncio.run(_run())


def test_expired_plan_cannot_confirm(
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
        return_value=_anime_entry(status="watching", score=0, episodes=1)
    )
    service = _build_service(
        db_session=db_session,
        clock=clock,
        resolver=resolver,
        mal=mal,
    )

    async def _run() -> None:
        plan = await service.create_plan(
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
        clock.set(clock.now() + timedelta(minutes=31))
        with pytest.raises(PlanExpiredError):
            service.confirm(
                user_id=user_id,
                plan_id=plan.plan_id,
                revision=1,
                plan_hash=plan.plan_hash,
            )

    asyncio.run(_run())


def test_mixed_bulk_with_not_found(
    db_session: Session,
    clock: FixedClock,
    user_id: str,
) -> None:
    resolver = AsyncMock()

    async def resolve_side_effect(*, user_id: str | None, request: Any) -> Any:
        if request.title == "Steins;Gate":
            return ResolvedOutcome(media=_steins_media(), candidates_considered=1)
        return NotFoundOutcome(query=request.title, reason="no match")

    resolver.resolve = AsyncMock(side_effect=resolve_side_effect)
    mal = AsyncMock()
    mal.get_anime_list_entry = AsyncMock(
        return_value=_anime_entry(status="watching", score=0, episodes=1)
    )
    service = _build_service(
        db_session=db_session,
        clock=clock,
        resolver=resolver,
        mal=mal,
    )

    async def _run() -> None:
        plan = await service.create_plan(
            user_id=user_id,
            request=CreateChangePlanRequest(
                changes=[
                    RequestedChange(
                        title="Steins;Gate",
                        media_type=MediaType.ANIME,
                        score=8,
                    ),
                    RequestedChange(
                        title="Totally Fake Title XYZ",
                        media_type=MediaType.ANIME,
                        score=5,
                    ),
                ]
            ),
        )
        kinds = {item.kind for item in plan.items}
        assert PlannedItemOutcomeKind.READY in kinds
        assert PlannedItemOutcomeKind.NOT_FOUND in kinds
        assert plan.confirmable is True

    asyncio.run(_run())
