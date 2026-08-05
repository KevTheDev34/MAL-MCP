"""Persistence helpers for command runs, plans, items, and apply attempts."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.commands.models import (
    AmbiguousPlannedItem,
    AppliedItemResult,
    InvalidPlannedItem,
    LookupFailedPlannedItem,
    NoOpPlannedItem,
    NotFoundPlannedItem,
    PlannedItemResult,
    ReadyPlannedItem,
)
from backend.app.db.models import (
    ApplicationAttempt,
    ChangePlanRecord,
    CommandRun,
    ItemReversion,
    PlannedItem,
)
from backend.app.domain.enums import (
    ApplicationAttemptState,
    ApplyResultKind,
    CommandSourceType,
    CommandState,
    MediaType,
    OutcomeCertainty,
    PlannedItemOutcomeKind,
    ReversionLinkState,
    ReversionStatus,
)
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.plans import PlanWarning
from backend.app.domain.requests import RequestedChange
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.resolver.models import ResolutionCandidate


class CommandPlanRepository:
    """Aggregate repository for the command/plan workflow."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_command_run(
        self,
        *,
        user_id: str,
        original_text: str | None,
        normalized_request_json: str,
        state: CommandState,
        now: datetime,
        source_type: CommandSourceType = CommandSourceType.API,
        parent_command_id: str | None = None,
    ) -> CommandRun:
        run = CommandRun(
            id=str(uuid4()),
            user_id=user_id,
            original_text=original_text,
            normalized_request_json=normalized_request_json,
            state=state.value,
            source_type=source_type.value,
            parent_command_id=parent_command_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(run)
        self._session.flush()
        return run

    def update_command_run_state(
        self,
        run: CommandRun,
        *,
        state: CommandState,
        now: datetime,
        cancel_reason: str | None = None,
    ) -> None:
        run.state = state.value
        run.updated_at = now
        if cancel_reason is not None:
            run.cancel_reason = cancel_reason
        self._session.flush()

    def create_plan(
        self,
        *,
        plan_id: UUID,
        command_run_id: str,
        user_id: str,
        revision: int,
        state: CommandState,
        plan_hash: str,
        canonical_plan_json: str,
        expires_at: datetime,
        now: datetime,
    ) -> ChangePlanRecord:
        plan = ChangePlanRecord(
            id=str(plan_id),
            command_run_id=command_run_id,
            user_id=user_id,
            revision=revision,
            state=state.value,
            plan_hash=plan_hash,
            canonical_plan_json=canonical_plan_json,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        self._session.add(plan)
        self._session.flush()
        return plan

    def add_planned_item(
        self,
        *,
        plan_id: str,
        item: PlannedItemResult,
    ) -> PlannedItem:
        row = PlannedItem(
            id=str(item.item_id),
            change_plan_id=plan_id,
            apply_order=item.apply_order,
            outcome_kind=str(item.kind),
            requested_change_json=item.requested.model_dump_json(),
            resolution_json=_resolution_json(item),
            mal_id=_mal_id(item),
            media_type=_media_type(item),
            canonical_title=_canonical_title(item),
            before_json=_before_json(item),
            after_json=_after_json(item),
            warnings_json=_warnings_json(item),
            is_noop=bool(getattr(item, "is_noop", False)),
            source_titles_json=json.dumps(item.source_titles, ensure_ascii=False),
            error_code=getattr(item, "error_code", None),
            error_message=getattr(item, "error_message", None),
            reversion_status=ReversionStatus.NONE.value,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_plan(self, plan_id: UUID) -> ChangePlanRecord | None:
        return self._session.get(ChangePlanRecord, str(plan_id))

    def get_command_run(self, run_id: str) -> CommandRun | None:
        return self._session.get(CommandRun, run_id)

    def list_items(self, plan_id: str) -> list[PlannedItem]:
        stmt = (
            select(PlannedItem)
            .where(PlannedItem.change_plan_id == plan_id)
            .order_by(PlannedItem.apply_order.asc())
        )
        return list(self._session.scalars(stmt).all())

    def list_attempts_for_item(self, planned_item_id: str) -> list[ApplicationAttempt]:
        stmt = (
            select(ApplicationAttempt)
            .where(ApplicationAttempt.planned_item_id == planned_item_id)
            .order_by(ApplicationAttempt.attempt_number.asc())
        )
        return list(self._session.scalars(stmt).all())

    def claim_for_apply(
        self,
        *,
        plan_id: UUID,
        revision: int,
        now: datetime,
    ) -> ChangePlanRecord | None:
        """Atomically transition awaiting_confirmation -> applying."""
        plan = self.get_plan(plan_id)
        if plan is None:
            return None
        if (
            plan.revision != revision
            or plan.state != CommandState.AWAITING_CONFIRMATION.value
            or plan.confirmed_at is None
        ):
            return None
        plan.state = CommandState.APPLYING.value
        plan.apply_started_at = now
        plan.updated_at = now
        self._session.flush()
        return plan

    def confirm_plan(
        self,
        plan: ChangePlanRecord,
        *,
        now: datetime,
    ) -> None:
        plan.confirmed_at = now
        plan.updated_at = now
        # State remains awaiting_confirmation until apply.
        self._session.flush()

    def set_plan_state(
        self,
        plan: ChangePlanRecord,
        *,
        state: CommandState,
        now: datetime,
        cancel_reason: str | None = None,
        apply_completed: bool = False,
    ) -> None:
        plan.state = state.value
        plan.updated_at = now
        if cancel_reason is not None:
            plan.cancel_reason = cancel_reason
        if apply_completed:
            plan.apply_completed_at = now
        self._session.flush()

    def create_attempt(
        self,
        *,
        planned_item_id: str,
        attempt_number: int,
        state: ApplicationAttemptState,
        now: datetime,
        idempotency_key: str,
        request_json: str | None = None,
        outcome_certainty: OutcomeCertainty = OutcomeCertainty.UNCERTAIN,
    ) -> ApplicationAttempt:
        attempt = ApplicationAttempt(
            id=str(uuid4()),
            planned_item_id=planned_item_id,
            attempt_number=attempt_number,
            state=state.value,
            idempotency_key=idempotency_key,
            outcome_certainty=outcome_certainty.value,
            request_json=request_json,
            started_at=now,
        )
        self._session.add(attempt)
        self._session.flush()
        return attempt

    def get_attempt_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ApplicationAttempt | None:
        stmt = select(ApplicationAttempt).where(
            ApplicationAttempt.idempotency_key == idempotency_key
        )
        return self._session.scalars(stmt).first()

    def finish_attempt(
        self,
        attempt: ApplicationAttempt,
        *,
        state: ApplicationAttemptState,
        now: datetime,
        update_response_json: str | None = None,
        verified_state_json: str | None = None,
        observed_state_json: str | None = None,
        error_type: str | None = None,
        error_message_redacted: str | None = None,
        outcome_certainty: OutcomeCertainty | None = None,
        field_mismatches_json: str | None = None,
    ) -> None:
        attempt.state = state.value
        attempt.finished_at = now
        if update_response_json is not None:
            attempt.update_response_json = update_response_json
        if verified_state_json is not None:
            attempt.verified_state_json = verified_state_json
        if observed_state_json is not None:
            attempt.observed_state_json = observed_state_json
        if error_type is not None:
            attempt.error_type = error_type
        if error_message_redacted is not None:
            attempt.error_message_redacted = error_message_redacted
        if outcome_certainty is not None:
            attempt.outcome_certainty = outcome_certainty.value
        if field_mismatches_json is not None:
            attempt.field_mismatches_json = field_mismatches_json
        self._session.flush()

    def set_item_apply_result(
        self,
        item: PlannedItem,
        *,
        result: ApplyResultKind,
    ) -> None:
        item.apply_result_kind = result.value
        self._session.flush()

    def set_item_reversion_status(
        self,
        item: PlannedItem,
        *,
        status: ReversionStatus,
    ) -> None:
        item.reversion_status = status.value
        self._session.flush()

    def get_planned_item(self, item_id: str) -> PlannedItem | None:
        return self._session.get(PlannedItem, item_id)

    def create_item_reversion(
        self,
        *,
        user_id: str,
        original_planned_item_id: str,
        original_command_run_id: str,
        reverse_command_run_id: str,
        reverse_planned_item_id: str,
        state: ReversionLinkState,
        now: datetime,
        conflict_json: str | None = None,
    ) -> ItemReversion:
        row = ItemReversion(
            id=str(uuid4()),
            user_id=user_id,
            original_planned_item_id=original_planned_item_id,
            original_command_run_id=original_command_run_id,
            reverse_command_run_id=reverse_command_run_id,
            reverse_planned_item_id=reverse_planned_item_id,
            state=state.value,
            conflict_json=conflict_json,
            created_at=now,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_reversions_for_original_item(
        self,
        original_planned_item_id: str,
    ) -> list[ItemReversion]:
        stmt = (
            select(ItemReversion)
            .where(ItemReversion.original_planned_item_id == original_planned_item_id)
            .order_by(ItemReversion.created_at.asc())
        )
        return list(self._session.scalars(stmt).all())

    def list_open_reversions_for_original_item(
        self,
        original_planned_item_id: str,
    ) -> list[ItemReversion]:
        stmt = select(ItemReversion).where(
            ItemReversion.original_planned_item_id == original_planned_item_id,
            ItemReversion.state == ReversionLinkState.PLANNED.value,
        )
        return list(self._session.scalars(stmt).all())

    def list_reversions_for_command(
        self,
        command_run_id: str,
    ) -> list[ItemReversion]:
        stmt = (
            select(ItemReversion)
            .where(
                (ItemReversion.original_command_run_id == command_run_id)
                | (ItemReversion.reverse_command_run_id == command_run_id)
            )
            .order_by(ItemReversion.created_at.asc())
        )
        return list(self._session.scalars(stmt).all())

    def mark_reversion_verified(
        self,
        reversion: ItemReversion,
        *,
        now: datetime,
        fully_restored: bool = True,
    ) -> None:
        reversion.state = ReversionLinkState.VERIFIED.value
        reversion.fully_restored = fully_restored
        reversion.reverted_at = now
        self._session.flush()

    def get_plan_by_command_run(
        self,
        command_run_id: str,
    ) -> ChangePlanRecord | None:
        stmt = (
            select(ChangePlanRecord)
            .where(ChangePlanRecord.command_run_id == command_run_id)
            .order_by(ChangePlanRecord.revision.desc())
        )
        return self._session.scalars(stmt).first()

    def list_command_runs(
        self,
        *,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        state: str | None = None,
        is_undo: bool | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[CommandRun]:
        stmt = select(CommandRun).where(CommandRun.user_id == user_id)
        if state is not None:
            stmt = stmt.where(CommandRun.state == state)
        if is_undo is True:
            stmt = stmt.where(CommandRun.parent_command_id.is_not(None))
        elif is_undo is False:
            stmt = stmt.where(CommandRun.parent_command_id.is_(None))
        if created_after is not None:
            stmt = stmt.where(CommandRun.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(CommandRun.created_at <= created_before)
        stmt = (
            stmt.order_by(CommandRun.created_at.desc(), CommandRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(stmt).all())

    def count_command_runs(
        self,
        *,
        user_id: str,
        state: str | None = None,
        is_undo: bool | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(CommandRun).where(
            CommandRun.user_id == user_id
        )
        if state is not None:
            stmt = stmt.where(CommandRun.state == state)
        if is_undo is True:
            stmt = stmt.where(CommandRun.parent_command_id.is_not(None))
        elif is_undo is False:
            stmt = stmt.where(CommandRun.parent_command_id.is_(None))
        if created_after is not None:
            stmt = stmt.where(CommandRun.created_at >= created_after)
        if created_before is not None:
            stmt = stmt.where(CommandRun.created_at <= created_before)
        return int(self._session.scalar(stmt) or 0)

    def items_to_results(self, rows: list[PlannedItem]) -> list[PlannedItemResult]:
        return [_row_to_item(row) for row in rows]

    def build_apply_results(
        self,
        rows: list[PlannedItem],
    ) -> list[AppliedItemResult]:
        results: list[AppliedItemResult] = []
        for row in rows:
            if row.apply_result_kind is None:
                continue
            attempts = self.list_attempts_for_item(row.id)
            latest = attempts[-1] if attempts else None
            verified = None
            observed = None
            if latest and latest.verified_state_json:
                verified = CurrentListState.model_validate_json(
                    latest.verified_state_json
                )
            if latest and latest.observed_state_json:
                observed = CurrentListState.model_validate_json(
                    latest.observed_state_json
                )
            results.append(
                AppliedItemResult(
                    item_id=UUID(row.id),
                    apply_order=row.apply_order,
                    result=ApplyResultKind(row.apply_result_kind),
                    mal_id=row.mal_id,
                    media_type=MediaType(row.media_type) if row.media_type else None,
                    canonical_title=row.canonical_title,
                    verified_state=verified,
                    observed_state=observed,
                    error_code=latest.error_type if latest else None,
                    error_message=latest.error_message_redacted if latest else None,
                    field_mismatches=(
                        list(json.loads(latest.field_mismatches_json))
                        if latest and latest.field_mismatches_json
                        else []
                    ),
                )
            )
        return results


def _resolution_json(item: PlannedItemResult) -> str | None:
    if isinstance(item, ReadyPlannedItem | NoOpPlannedItem):
        return item.media.model_dump_json()
    if isinstance(item, AmbiguousPlannedItem):
        return json.dumps(
            {
                "query": item.query,
                "reason": item.reason,
                "candidates": [c.model_dump(mode="json") for c in item.candidates],
            },
            ensure_ascii=False,
        )
    if isinstance(item, NotFoundPlannedItem):
        return json.dumps(
            {
                "query": item.query,
                "reason": item.reason,
                "media_type": item.media_type.value if item.media_type else None,
            },
            ensure_ascii=False,
        )
    if isinstance(item, InvalidPlannedItem | LookupFailedPlannedItem) and item.media:
        return item.media.model_dump_json()
    return None


def _mal_id(item: PlannedItemResult) -> int | None:
    if isinstance(item, ReadyPlannedItem | NoOpPlannedItem):
        return item.media.mal_id
    if isinstance(item, InvalidPlannedItem | LookupFailedPlannedItem):
        return item.media.mal_id if item.media else None
    return None


def _media_type(item: PlannedItemResult) -> str | None:
    if isinstance(item, ReadyPlannedItem | NoOpPlannedItem):
        return item.media.media_type.value
    if isinstance(item, InvalidPlannedItem | LookupFailedPlannedItem):
        return item.media.media_type.value if item.media else None
    if isinstance(item, NotFoundPlannedItem):
        return item.media_type.value if item.media_type else None
    return None


def _canonical_title(item: PlannedItemResult) -> str | None:
    if isinstance(item, ReadyPlannedItem | NoOpPlannedItem):
        return item.media.canonical_title
    if isinstance(item, InvalidPlannedItem | LookupFailedPlannedItem):
        return item.media.canonical_title if item.media else None
    return None


def _before_json(item: PlannedItemResult) -> str | None:
    if isinstance(item, ReadyPlannedItem | NoOpPlannedItem):
        return item.before.model_dump_json()
    if isinstance(item, InvalidPlannedItem) and item.before is not None:
        return item.before.model_dump_json()
    return None


def _after_json(item: PlannedItemResult) -> str | None:
    if isinstance(item, ReadyPlannedItem | NoOpPlannedItem):
        return item.after.model_dump_json()
    return None


def _warnings_json(item: PlannedItemResult) -> str:
    if isinstance(item, ReadyPlannedItem | NoOpPlannedItem):
        return json.dumps(
            [w.model_dump(mode="json") for w in item.warnings],
            ensure_ascii=False,
        )
    return "[]"


def _row_to_item(row: PlannedItem) -> PlannedItemResult:
    requested = RequestedChange.model_validate_json(row.requested_change_json)
    source_titles: list[str] = []
    if row.source_titles_json:
        source_titles = list(json.loads(row.source_titles_json))
    kind = PlannedItemOutcomeKind(row.outcome_kind)
    warnings = [
        PlanWarning.model_validate(w) for w in json.loads(row.warnings_json or "[]")
    ]

    if kind is PlannedItemOutcomeKind.READY:
        assert row.resolution_json and row.before_json and row.after_json
        return ReadyPlannedItem(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            requested=requested,
            source_titles=source_titles,
            media=ResolvedMedia.model_validate_json(row.resolution_json),
            before=CurrentListState.model_validate_json(row.before_json),
            after=ProposedListState.model_validate_json(row.after_json),
            warnings=warnings,
        )
    if kind is PlannedItemOutcomeKind.NOOP:
        assert row.resolution_json and row.before_json and row.after_json
        return NoOpPlannedItem(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            requested=requested,
            source_titles=source_titles,
            media=ResolvedMedia.model_validate_json(row.resolution_json),
            before=CurrentListState.model_validate_json(row.before_json),
            after=ProposedListState.model_validate_json(row.after_json),
            warnings=warnings,
        )
    if kind is PlannedItemOutcomeKind.AMBIGUOUS:
        payload = json.loads(row.resolution_json or "{}")
        return AmbiguousPlannedItem(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            requested=requested,
            source_titles=source_titles,
            query=payload.get("query", requested.title),
            reason=payload.get("reason", ""),
            candidates=[
                ResolutionCandidate.model_validate(c)
                for c in payload.get("candidates", [])
            ],
        )
    if kind is PlannedItemOutcomeKind.NOT_FOUND:
        payload = json.loads(row.resolution_json or "{}")
        mt = payload.get("media_type")
        return NotFoundPlannedItem(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            requested=requested,
            source_titles=source_titles,
            query=payload.get("query", requested.title),
            media_type=MediaType(mt) if mt else None,
            reason=payload.get("reason", ""),
        )
    if kind is PlannedItemOutcomeKind.INVALID:
        media = (
            ResolvedMedia.model_validate_json(row.resolution_json)
            if row.resolution_json
            else None
        )
        before = (
            CurrentListState.model_validate_json(row.before_json)
            if row.before_json
            else None
        )
        return InvalidPlannedItem(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            requested=requested,
            source_titles=source_titles,
            error_code=row.error_code or "invalid",
            error_message=row.error_message or "Invalid change",
            media=media,
            before=before,
        )
    media = (
        ResolvedMedia.model_validate_json(row.resolution_json)
        if row.resolution_json
        else None
    )
    return LookupFailedPlannedItem(
        item_id=UUID(row.id),
        apply_order=row.apply_order,
        requested=requested,
        source_titles=source_titles,
        media=media,
        error_code=row.error_code or "lookup_failed",
        error_message=row.error_message or "Current state lookup failed",
    )
