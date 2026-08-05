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
from backend.app.commands.history import HistoryService
from backend.app.commands.models import (
    ApplyPlanResponse,
    ChangePlanView,
    ConfirmPlanResponse,
    CreateChangePlanRequest,
    CreateUndoPlanRequest,
    HistoryCommandDetail,
    HistoryListResponse,
    RecoveryResult,
    UndoPlanResponse,
)
from backend.app.commands.planner import ChangePlanner
from backend.app.commands.recovery import ApplicationRecoveryService
from backend.app.commands.undo import UndoService
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.domain.enums import CommandSourceType, CommandState, MediaType
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
        recovery: ApplicationRecoveryService | None = None,
        undo: UndoService | None = None,
        history: HistoryService | None = None,
        source_type: CommandSourceType = CommandSourceType.API,
    ) -> None:
        self._planner = planner
        self._confirmation = confirmation
        self._executor = executor
        self._repository = repository
        self._clock = clock
        self._recovery = recovery
        self._undo = undo
        self._history = history or HistoryService(repository=repository)
        self._source_type = source_type

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
            source_type=self._source_type,
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

    async def recover(
        self,
        *,
        user_id: str,
        plan_id: UUID,
        revision: int,
    ) -> RecoveryResult:
        if self._recovery is None:
            raise PlanNotApplyableError("Recovery service is not configured")
        return await self._recovery.recover_plan(
            user_id=user_id,
            plan_id=plan_id,
            revision=revision,
        )

    def list_history(
        self,
        *,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        state: str | None = None,
        is_undo: bool | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        media_type: MediaType | None = None,
        mal_id: int | None = None,
    ) -> HistoryListResponse:
        return self._history.list_history(
            user_id=user_id,
            limit=limit,
            offset=offset,
            state=state,
            is_undo=is_undo,
            created_after=created_after,
            created_before=created_before,
            media_type=media_type,
            mal_id=mal_id,
        )

    def get_command_history(
        self,
        *,
        user_id: str,
        command_id: UUID,
    ) -> HistoryCommandDetail:
        return self._history.get_command_history(
            user_id=user_id,
            command_id=command_id,
        )

    def get_plan_history(
        self,
        *,
        user_id: str,
        plan_id: UUID,
    ) -> HistoryCommandDetail:
        return self._history.get_plan_history(user_id=user_id, plan_id=plan_id)

    async def create_undo_plan(
        self,
        *,
        user_id: str,
        command_id: UUID,
        request: CreateUndoPlanRequest | None = None,
    ) -> UndoPlanResponse:
        if self._undo is None:
            raise PlanNotApplyableError("Undo service is not configured")
        return await self._undo.create_undo_plan_for_command(
            user_id=user_id,
            command_id=command_id,
            request=request,
        )

    async def create_undo_plan_for_item(
        self,
        *,
        user_id: str,
        plan_id: UUID,
        item_id: UUID,
        reason: str | None = None,
    ) -> UndoPlanResponse:
        if self._undo is None:
            raise PlanNotApplyableError("Undo service is not configured")
        return await self._undo.create_undo_plan_for_item(
            user_id=user_id,
            plan_id=plan_id,
            item_id=item_id,
            reason=reason,
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
