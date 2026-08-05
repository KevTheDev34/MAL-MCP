"""Read-only command history assembly for Phase 7."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from backend.app.commands.errors import HistoryNotFoundError, PlanOwnershipError
from backend.app.commands.models import (
    AttemptHistoryView,
    ChangePlanView,
    HistoryCommandDetail,
    HistoryCommandSummary,
    HistoryItemView,
    HistoryListResponse,
    ReversionHistoryView,
)
from backend.app.commands.undo import changed_fields
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.domain.enums import (
    ApplyResultKind,
    CommandSourceType,
    CommandState,
    MediaType,
    PlannedItemOutcomeKind,
    ReversionLinkState,
    ReversionStatus,
)
from backend.app.domain.requests import RequestedChange
from backend.app.domain.state import CurrentListState, ProposedListState


class HistoryService:
    """Assemble paginated and detailed command history views."""

    def __init__(self, *, repository: CommandPlanRepository) -> None:
        self._repository = repository

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
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        # Over-fetch when media/mal filters require plan-item inspection.
        fetch_limit = limit if media_type is None and mal_id is None else limit * 5
        runs = self._repository.list_command_runs(
            user_id=user_id,
            limit=fetch_limit + offset,
            offset=0,
            state=state,
            is_undo=is_undo,
            created_after=created_after,
            created_before=created_before,
        )
        summaries: list[HistoryCommandSummary] = []
        for run in runs:
            plan = self._repository.get_plan_by_command_run(run.id)
            items = self._repository.list_items(plan.id) if plan else []
            if media_type is not None:
                if not any(
                    i.media_type == media_type.value for i in items if i.media_type
                ):
                    continue
            if mal_id is not None:
                if not any(i.mal_id == mal_id for i in items):
                    continue
            verified_count = sum(
                1
                for i in items
                if i.apply_result_kind == ApplyResultKind.VERIFIED.value
            )
            summaries.append(
                HistoryCommandSummary(
                    command_id=UUID(run.id),
                    state=CommandState(run.state),
                    source_type=CommandSourceType(run.source_type),
                    parent_command_id=(
                        UUID(run.parent_command_id) if run.parent_command_id else None
                    ),
                    is_undo=run.parent_command_id is not None,
                    original_text=run.original_text,
                    plan_id=UUID(plan.id) if plan else None,
                    revision=plan.revision if plan else None,
                    created_at=_as_utc(run.created_at),
                    item_count=len(items),
                    verified_count=verified_count,
                )
            )
        total = len(summaries)
        page = summaries[offset : offset + limit]
        return HistoryListResponse(
            items=page,
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_command_history(
        self,
        *,
        user_id: str,
        command_id: UUID,
    ) -> HistoryCommandDetail:
        run = self._repository.get_command_run(str(command_id))
        if run is None or run.user_id != user_id:
            raise HistoryNotFoundError(f"Command {command_id} was not found")
        return self._detail_for_run(run)

    def get_plan_history(
        self,
        *,
        user_id: str,
        plan_id: UUID,
    ) -> HistoryCommandDetail:
        plan = self._repository.get_plan(plan_id)
        if plan is None:
            raise HistoryNotFoundError(f"Plan {plan_id} was not found")
        if plan.user_id != user_id:
            raise PlanOwnershipError("Plan does not belong to the authenticated user")
        run = self._repository.get_command_run(plan.command_run_id)
        if run is None:
            raise HistoryNotFoundError("Command run missing for plan")
        return self._detail_for_run(run)

    def _detail_for_run(self, run: object) -> HistoryCommandDetail:
        from backend.app.db.models import CommandRun

        assert isinstance(run, CommandRun)
        plan = self._repository.get_plan_by_command_run(run.id)
        plan_view: ChangePlanView | None = None
        item_views: list[HistoryItemView] = []
        if plan is not None:
            item_rows = self._repository.list_items(plan.id)
            items = self._repository.items_to_results(item_rows)
            apply_results = self._repository.build_apply_results(item_rows)
            confirmable = (
                plan.state == CommandState.AWAITING_CONFIRMATION.value
                and any(str(i.kind) == "ready" for i in items)
            )
            applyable = (
                plan.confirmed_at is not None
                and plan.state == CommandState.AWAITING_CONFIRMATION.value
            )
            plan_view = ChangePlanView(
                plan_id=UUID(plan.id),
                revision=plan.revision,
                state=CommandState(plan.state),
                original_text=run.original_text,
                expires_at=_as_utc(plan.expires_at),
                confirmed_at=(
                    _as_utc(plan.confirmed_at) if plan.confirmed_at else None
                ),
                plan_hash=plan.plan_hash,
                confirmation_required=confirmable or applyable,
                confirmable=confirmable and plan.confirmed_at is None,
                applyable=applyable,
                items=items,
                apply_results=apply_results,
                created_at=_as_utc(plan.created_at),
            )
            for row in item_rows:
                attempts = [
                    AttemptHistoryView(
                        attempt_id=UUID(a.id),
                        attempt_number=a.attempt_number,
                        state=a.state,
                        idempotency_key=a.idempotency_key,
                        outcome_certainty=a.outcome_certainty,
                        request=(
                            json.loads(a.request_json) if a.request_json else None
                        ),
                        update_response=(
                            json.loads(a.update_response_json)
                            if a.update_response_json
                            else None
                        ),
                        verified_state=(
                            CurrentListState.model_validate_json(a.verified_state_json)
                            if a.verified_state_json
                            else None
                        ),
                        observed_state=(
                            CurrentListState.model_validate_json(a.observed_state_json)
                            if a.observed_state_json
                            else None
                        ),
                        field_mismatches=(
                            list(json.loads(a.field_mismatches_json))
                            if a.field_mismatches_json
                            else []
                        ),
                        error_type=a.error_type,
                        error_message=a.error_message_redacted,
                        started_at=_as_utc(a.started_at),
                        finished_at=(
                            _as_utc(a.finished_at) if a.finished_at else None
                        ),
                    )
                    for a in self._repository.list_attempts_for_item(row.id)
                ]
                before = (
                    CurrentListState.model_validate_json(row.before_json)
                    if row.before_json
                    else None
                )
                after = (
                    ProposedListState.model_validate_json(row.after_json)
                    if row.after_json
                    else None
                )
                undo_eligible = _undo_eligible(row, before, after)
                item_views.append(
                    HistoryItemView(
                        item_id=UUID(row.id),
                        apply_order=row.apply_order,
                        outcome_kind=PlannedItemOutcomeKind(row.outcome_kind),
                        apply_result_kind=(
                            ApplyResultKind(row.apply_result_kind)
                            if row.apply_result_kind
                            else None
                        ),
                        reversion_status=ReversionStatus(row.reversion_status),
                        mal_id=row.mal_id,
                        media_type=(
                            MediaType(row.media_type) if row.media_type else None
                        ),
                        canonical_title=row.canonical_title,
                        requested=RequestedChange.model_validate_json(
                            row.requested_change_json
                        ),
                        planned_before=before,
                        proposed_after=after,
                        is_noop=row.is_noop,
                        undo_eligible=undo_eligible,
                        attempts=attempts,
                    )
                )

        reversions = [
            ReversionHistoryView(
                reversion_id=UUID(r.id),
                original_planned_item_id=UUID(r.original_planned_item_id),
                reverse_planned_item_id=UUID(r.reverse_planned_item_id),
                reverse_command_id=UUID(r.reverse_command_run_id),
                state=ReversionLinkState(r.state),
                fully_restored=r.fully_restored,
                created_at=_as_utc(r.created_at),
                reverted_at=_as_utc(r.reverted_at) if r.reverted_at else None,
            )
            for r in self._repository.list_reversions_for_command(run.id)
        ]

        try:
            normalized = json.loads(run.normalized_request_json)
            if not isinstance(normalized, list):
                normalized = [normalized]
        except json.JSONDecodeError:
            normalized = []

        return HistoryCommandDetail(
            command_id=UUID(run.id),
            state=CommandState(run.state),
            source_type=CommandSourceType(run.source_type),
            parent_command_id=(
                UUID(run.parent_command_id) if run.parent_command_id else None
            ),
            is_undo=run.parent_command_id is not None,
            original_text=run.original_text,
            normalized_request=normalized,
            created_at=_as_utc(run.created_at),
            updated_at=_as_utc(run.updated_at),
            plan=plan_view,
            items=item_views,
            reversions=reversions,
        )


def _undo_eligible(
    row: object,
    before: CurrentListState | None,
    after: ProposedListState | None,
) -> bool:
    from backend.app.db.models import PlannedItem

    assert isinstance(row, PlannedItem)
    if row.apply_result_kind != ApplyResultKind.VERIFIED.value:
        return False
    if row.is_noop or row.outcome_kind != PlannedItemOutcomeKind.READY.value:
        return False
    if row.reversion_status in (
        ReversionStatus.REVERTED.value,
        ReversionStatus.UNDO_PLANNED.value,
        ReversionStatus.NOT_REVERSIBLE.value,
    ):
        return False
    if before is None or after is None:
        return False
    if not before.is_on_list:
        return False
    return bool(changed_fields(before, after))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
