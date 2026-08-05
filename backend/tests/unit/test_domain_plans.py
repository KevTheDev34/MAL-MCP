"""Unit tests for planned changes and change plans."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.domain.enums import (
    AnimeStatus,
    CommandState,
    DomainErrorCode,
    MediaType,
    PlanWarningCode,
)
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.plans import ChangePlan, PlannedChange, PlanWarning
from backend.app.domain.serialization import canonical_domain_json
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.tests.unit.domain_test_helpers import domain_error_from


def _media() -> ResolvedMedia:
    return ResolvedMedia(
        mal_id=9253,
        media_type=MediaType.ANIME,
        canonical_title="Steins;Gate",
        confidence=0.99,
    )


def _planned_change(*, change_id=None) -> PlannedChange:
    return PlannedChange(
        change_id=change_id or uuid4(),
        media=_media(),
        before=CurrentListState(
            media_type=MediaType.ANIME,
            is_on_list=True,
            status=AnimeStatus.WATCHING,
            score=8,
            episode_progress=10,
        ),
        after=ProposedListState(
            media_type=MediaType.ANIME,
            status=AnimeStatus.COMPLETED,
            score=9,
            episode_progress=24,
        ),
        warnings=[
            PlanWarning(
                code=PlanWarningCode.SCORE_OVERWRITE,
                message="Score will change from 8 to 9",
                field="score",
            )
        ],
    )


def test_valid_planned_change() -> None:
    change = _planned_change()
    assert change.requires_confirmation is True
    assert change.is_noop is False


def test_valid_multi_change_plan() -> None:
    plan = ChangePlan(
        plan_id=uuid4(),
        revision=1,
        user_id="user-1",
        state=CommandState.PLANNED,
        original_text="I finished Steins;Gate",
        changes=[_planned_change(), _planned_change()],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert len(plan.changes) == 2
    assert plan.plan_hash is None
    assert plan.expires_at is None


def test_empty_plan_allowed() -> None:
    plan = ChangePlan(
        plan_id=uuid4(),
        revision=1,
        user_id="user-1",
        state=CommandState.PLANNED,
        changes=[],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert plan.changes == []


def test_duplicate_change_ids_rejected() -> None:
    change_id = uuid4()
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        ChangePlan(
            plan_id=uuid4(),
            revision=1,
            user_id="user-1",
            state=CommandState.PLANNED,
            changes=[
                _planned_change(change_id=change_id),
                _planned_change(change_id=change_id),
            ],
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.DUPLICATE_CHANGE_ID


def test_invalid_revision_rejected() -> None:
    with pytest.raises(ValidationError):
        ChangePlan(
            plan_id=uuid4(),
            revision=0,
            user_id="user-1",
            state=CommandState.PLANNED,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_naive_created_at_rejected() -> None:
    with pytest.raises((DomainValidationError, ValidationError)) as exc_info:
        ChangePlan(
            plan_id=uuid4(),
            revision=1,
            user_id="user-1",
            state=CommandState.PLANNED,
            created_at=datetime(2026, 1, 1),
        )
    assert domain_error_from(exc_info).code is DomainErrorCode.TIMEZONE_REQUIRED


def test_stable_canonical_json() -> None:
    plan_id = uuid4()
    change_id = uuid4()
    created = datetime(2026, 1, 1, tzinfo=UTC)
    plan = ChangePlan(
        plan_id=plan_id,
        revision=1,
        user_id="user-1",
        state=CommandState.PLANNED,
        changes=[_planned_change(change_id=change_id)],
        created_at=created,
    )
    first = canonical_domain_json(plan)
    second = canonical_domain_json(plan)
    assert first == second
    assert '"plan_id"' in first
    assert plan_id.hex in first.replace("-", "") or str(plan_id) in first
