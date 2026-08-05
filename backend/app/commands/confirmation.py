"""Server-side plan confirmation (does not apply)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from backend.app.commands.errors import (
    PlanCanceledError,
    PlanExpiredError,
    PlanHashMismatchError,
    PlanNotConfirmableError,
    PlanNotFoundError,
    PlanOwnershipError,
    PlanRevisionMismatchError,
)
from backend.app.commands.models import ConfirmPlanResponse
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.domain.enums import CommandState, PlannedItemOutcomeKind
from backend.app.services.clock import Clock


class PlanConfirmationService:
    """Bind confirmation to an exact stored plan revision and hash."""

    def __init__(
        self,
        *,
        repository: CommandPlanRepository,
        clock: Clock,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def confirm(
        self,
        *,
        user_id: str,
        plan_id: UUID,
        revision: int,
        plan_hash: str,
    ) -> ConfirmPlanResponse:
        plan = self._repository.get_plan(plan_id)
        if plan is None:
            raise PlanNotFoundError(f"Plan {plan_id} was not found")
        if plan.user_id != user_id:
            raise PlanOwnershipError("Plan does not belong to the authenticated user")
        if plan.state == CommandState.REJECTED.value:
            raise PlanCanceledError("Plan was canceled and cannot be confirmed")
        if plan.revision != revision:
            raise PlanRevisionMismatchError(
                f"Plan revision mismatch: expected {plan.revision}, got {revision}"
            )
        if plan.plan_hash != plan_hash:
            raise PlanHashMismatchError("Plan hash does not match the stored plan")

        now = self._clock.now()
        expires_at = _as_utc(plan.expires_at)
        if plan.confirmed_at is None and expires_at <= now:
            raise PlanExpiredError("Plan has expired and cannot be confirmed")

        if plan.state != CommandState.AWAITING_CONFIRMATION.value:
            raise PlanNotConfirmableError(
                f"Plan state {plan.state!r} is not confirmable"
            )

        items = self._repository.list_items(plan.id)
        has_ready = any(
            row.outcome_kind == PlannedItemOutcomeKind.READY.value for row in items
        )
        if not has_ready:
            raise PlanNotConfirmableError(
                "Plan has no applyable ready changes to confirm"
            )

        # Idempotent re-confirmation of the same revision/hash.
        if plan.confirmed_at is not None:
            return ConfirmPlanResponse(
                plan_id=plan_id,
                revision=plan.revision,
                state=CommandState(plan.state),
                confirmed_at=_as_utc(plan.confirmed_at),
                applyable=True,
                plan_hash=plan.plan_hash,
            )

        self._repository.confirm_plan(plan, now=now)
        run = self._repository.get_command_run(plan.command_run_id)
        if run is not None:
            self._repository.update_command_run_state(
                run,
                state=CommandState.AWAITING_CONFIRMATION,
                now=now,
            )
        self._repository._session.commit()

        return ConfirmPlanResponse(
            plan_id=plan_id,
            revision=plan.revision,
            state=CommandState(plan.state),
            confirmed_at=now,
            applyable=True,
            plan_hash=plan.plan_hash,
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
