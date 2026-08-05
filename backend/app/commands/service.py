"""Command application facade used by API routes and diagnostic scripts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from backend.app.commands.confirmation import PlanConfirmationService
from backend.app.commands.errors import (
    PlanNotApplyableError,
    PlanNotFoundError,
    PlanOwnershipError,
)
from backend.app.commands.executor import ChangePlanExecutor
from backend.app.commands.models import (
    ApplyPlanResponse,
    ChangePlanView,
    ConfirmPlanResponse,
    CreateChangePlanRequest,
)
from backend.app.commands.planner import ChangePlanner
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.domain.enums import CommandState
from backend.app.domain.transitions import validate_transition
from backend.app.services.clock import Clock


class CommandApplicationService:
    """Thin orchestration layer over planner, confirmation, and executor."""

    def __init__(
        self,
        *,
        planner: ChangePlanner,
        confirmation: PlanConfirmationService,
        executor: ChangePlanExecutor,
        repository: CommandPlanRepository,
        clock: Clock,
    ) -> None:
        self._planner = planner
        self._confirmation = confirmation
        self._executor = executor
        self._repository = repository
        self._clock = clock

    async def create_plan(
        self,
        *,
        user_id: str,
        request: CreateChangePlanRequest,
    ) -> ChangePlanView:
        return await self._planner.create_plan(
            user_id=user_id,
            requested_changes=request.changes,
            original_text=request.original_text,
        )

    def get_plan(self, *, user_id: str, plan_id: UUID) -> ChangePlanView:
        plan = self._repository.get_plan(plan_id)
        if plan is None:
            raise PlanNotFoundError(f"Plan {plan_id} was not found")
        if plan.user_id != user_id:
            raise PlanOwnershipError("Plan does not belong to the authenticated user")
        items = self._repository.items_to_results(self._repository.list_items(plan.id))
        item_rows = self._repository.list_items(plan.id)
        apply_results = self._repository.build_apply_results(item_rows)
        run = self._repository.get_command_run(plan.command_run_id)
        confirmable = plan.state == CommandState.AWAITING_CONFIRMATION.value and any(
            str(i.kind) == "ready" for i in items
        )
        applyable = (
            plan.confirmed_at is not None
            and plan.state == CommandState.AWAITING_CONFIRMATION.value
        )
        return ChangePlanView(
            plan_id=UUID(plan.id),
            revision=plan.revision,
            state=CommandState(plan.state),
            original_text=run.original_text if run else None,
            expires_at=_as_utc(plan.expires_at),
            confirmed_at=_as_utc(plan.confirmed_at) if plan.confirmed_at else None,
            plan_hash=plan.plan_hash,
            confirmation_required=confirmable or applyable,
            confirmable=confirmable and plan.confirmed_at is None,
            applyable=applyable,
            items=items,
            apply_results=apply_results,
            created_at=_as_utc(plan.created_at),
        )

    def confirm(
        self,
        *,
        user_id: str,
        plan_id: UUID,
        revision: int,
        plan_hash: str,
    ) -> ConfirmPlanResponse:
        return self._confirmation.confirm(
            user_id=user_id,
            plan_id=plan_id,
            revision=revision,
            plan_hash=plan_hash,
        )

    async def apply(
        self,
        *,
        user_id: str,
        plan_id: UUID,
        revision: int,
    ) -> ApplyPlanResponse:
        return await self._executor.apply(
            user_id=user_id,
            plan_id=plan_id,
            revision=revision,
        )

    def cancel(self, *, user_id: str, plan_id: UUID) -> ChangePlanView:
        plan = self._repository.get_plan(plan_id)
        if plan is None:
            raise PlanNotFoundError(f"Plan {plan_id} was not found")
        if plan.user_id != user_id:
            raise PlanOwnershipError("Plan does not belong to the authenticated user")

        now = self._clock.now()
        if plan.state == CommandState.REJECTED.value:
            return self.get_plan(user_id=user_id, plan_id=plan_id)

        if plan.state in (
            CommandState.APPLYING.value,
            CommandState.VERIFIED.value,
            CommandState.PARTIALLY_APPLIED.value,
            CommandState.FAILED.value,
            CommandState.REVERTED.value,
        ):
            raise PlanNotApplyableError(
                "Applied or applying plans cannot be canceled"
            )

        current = CommandState(plan.state)
        validate_transition(current, CommandState.REJECTED)
        self._repository.set_plan_state(
            plan,
            state=CommandState.REJECTED,
            now=now,
            cancel_reason="canceled_by_user",
        )
        run = self._repository.get_command_run(plan.command_run_id)
        if run is not None:
            run_state = CommandState(run.state)
            if run_state is not CommandState.REJECTED:
                validate_transition(run_state, CommandState.REJECTED)
                self._repository.update_command_run_state(
                    run,
                    state=CommandState.REJECTED,
                    now=now,
                    cancel_reason="canceled_by_user",
                )
        self._repository._session.commit()
        return self.get_plan(user_id=user_id, plan_id=plan_id)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
