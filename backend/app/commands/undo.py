"""Field-level undo via reverse change plans (Phase 7)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from backend.app.commands.audit import sanitize_original_text
from backend.app.commands.errors import (
    HistoryNotFoundError,
    PlanOwnershipError,
    UndoAlreadyCompletedError,
    UndoInProgressError,
    UndoNotEligibleError,
    UndoTargetMissingError,
)
from backend.app.commands.hashing import compute_plan_hash
from backend.app.commands.models import (
    ChangePlanView,
    CreateUndoPlanRequest,
    PlannedItemResult,
    ReadyPlannedItem,
    UndoItemPreview,
    UndoPlanResponse,
)
from backend.app.db.models import CommandRun, PlannedItem
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.domain.enums import (
    ApplyResultKind,
    CommandSourceType,
    CommandState,
    MediaType,
    PlannedItemOutcomeKind,
    ReversionLinkState,
    ReversionStatus,
    UndoItemOutcomeKind,
)
from backend.app.domain.media import ResolvedMedia
from backend.app.domain.requests import RequestedChange
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.domain.transitions import validate_transition
from backend.app.mal.client import MalClient
from backend.app.mal.domain_mapping import list_entry_or_none_to_current_state
from backend.app.mal.errors import MalError
from backend.app.services.clock import Clock

_MUTABLE_FIELDS: tuple[str, ...] = (
    "status",
    "score",
    "episode_progress",
    "chapter_progress",
    "volume_progress",
)


class UndoService:
    """Build reverse plans that restore only fields changed by the original item."""

    def __init__(
        self,
        *,
        repository: CommandPlanRepository,
        mal_client: MalClient,
        clock: Clock,
        plan_expiration_minutes: int = 30,
        source_type: CommandSourceType = CommandSourceType.API,
    ) -> None:
        self._repository = repository
        self._mal = mal_client
        self._clock = clock
        self._plan_expiration_minutes = plan_expiration_minutes
        self._source_type = source_type

    async def create_undo_plan_for_command(
        self,
        *,
        user_id: str,
        command_id: UUID,
        request: CreateUndoPlanRequest | None = None,
    ) -> UndoPlanResponse:
        run = self._repository.get_command_run(str(command_id))
        if run is None or run.user_id != user_id:
            raise HistoryNotFoundError(f"Command {command_id} was not found")
        plan = self._repository.get_plan_by_command_run(run.id)
        if plan is None:
            raise HistoryNotFoundError(f"No plan found for command {command_id}")
        items = self._repository.list_items(plan.id)
        selected = _select_items(items, request.item_ids if request else None)
        if not selected:
            raise UndoNotEligibleError("No planned items selected for undo")
        return await self._create_undo_plan(
            user_id=user_id,
            original_run=run,
            selected=selected,
            reason=request.reason if request else None,
        )

    async def create_undo_plan_for_item(
        self,
        *,
        user_id: str,
        plan_id: UUID,
        item_id: UUID,
        reason: str | None = None,
    ) -> UndoPlanResponse:
        plan = self._repository.get_plan(plan_id)
        if plan is None:
            raise UndoTargetMissingError(f"Plan {plan_id} was not found")
        if plan.user_id != user_id:
            raise PlanOwnershipError("Plan does not belong to the authenticated user")
        run = self._repository.get_command_run(plan.command_run_id)
        if run is None:
            raise HistoryNotFoundError("Command run missing for plan")
        row = self._repository.get_planned_item(str(item_id))
        if row is None or row.change_plan_id != plan.id:
            raise UndoTargetMissingError(f"Item {item_id} was not found on plan")
        return await self._create_undo_plan(
            user_id=user_id,
            original_run=run,
            selected=[row],
            reason=reason,
        )

    async def _create_undo_plan(
        self,
        *,
        user_id: str,
        original_run: CommandRun,
        selected: list[PlannedItem],
        reason: str | None,
    ) -> UndoPlanResponse:
        previews: list[UndoItemPreview] = []
        ready_pairs: list[tuple[PlannedItem, ReadyPlannedItem, list[str]]] = []

        for row in selected:
            preview = await self._evaluate_item(row)
            previews.append(preview)
            if preview.outcome is UndoItemOutcomeKind.READY:
                assert preview.proposed_restore is not None
                assert row.resolution_json and row.mal_id and row.media_type
                media = ResolvedMedia.model_validate_json(row.resolution_json)
                requested = _requested_from_restore(
                    title=row.canonical_title or media.canonical_title,
                    media_type=MediaType(row.media_type),
                    restore=preview.proposed_restore,
                    changed_fields=preview.changed_fields,
                )
                reverse_item = ReadyPlannedItem(
                    item_id=uuid4(),
                    apply_order=len(ready_pairs),
                    requested=requested,
                    source_titles=[requested.title],
                    media=media,
                    before=CurrentListState.model_validate(
                        preview.undo_check_observed.model_dump()
                        if preview.undo_check_observed
                        else {}
                    )
                    if preview.undo_check_observed
                    else CurrentListState.model_validate_json(row.after_json or "{}"),
                    after=preview.proposed_restore,
                    warnings=[],
                )
                # Prefer live observed as before-state for stale checks.
                if preview.undo_check_observed is not None:
                    reverse_item = reverse_item.model_copy(
                        update={"before": preview.undo_check_observed}
                    )
                ready_pairs.append((row, reverse_item, preview.changed_fields))
                preview.reverse_item_id = reverse_item.item_id

        if not ready_pairs:
            # Surface a typed error when nothing is undoable.
            if all(p.outcome is UndoItemOutcomeKind.ALREADY_REVERTED for p in previews):
                raise UndoAlreadyCompletedError("Selected items are already reverted")
            if all(p.outcome is UndoItemOutcomeKind.CONFLICT for p in previews):
                raise UndoNotEligibleError(
                    "All selected items have same-field conflicts; create a new plan"
                )
            raise UndoNotEligibleError("No eligible items for undo")

        now = self._clock.now()
        request_payload = [
            {
                "original_item_id": str(row.id),
                "reverse_item_id": str(item.item_id),
                "changed_fields": fields,
            }
            for row, item, fields in ready_pairs
        ]
        if reason:
            cleaned_reason = sanitize_original_text(reason)
            if cleaned_reason is not None:
                request_payload.append({"reason": cleaned_reason})

        reverse_run = self._repository.create_command_run(
            user_id=user_id,
            original_text=sanitize_original_text(
                f"undo:{original_run.id}" + (f" ({reason})" if reason else "")
            ),
            normalized_request_json=json.dumps(
                request_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            state=CommandState.RECEIVED,
            now=now,
            source_type=self._source_type,
            parent_command_id=original_run.id,
        )
        for state in (
            CommandState.PARSED,
            CommandState.RESOLVING,
            CommandState.PLANNED,
            CommandState.AWAITING_CONFIRMATION,
        ):
            current = CommandState(reverse_run.state)
            validate_transition(current, state)
            self._repository.update_command_run_state(
                reverse_run,
                state=state,
                now=now,
            )

        plan_id = uuid4()
        ready_items: list[PlannedItemResult] = [
            item for _, item, _ in ready_pairs
        ]
        plan_hash = compute_plan_hash(
            plan_id=plan_id,
            revision=1,
            user_id=user_id,
            items=ready_items,
        )
        canonical = json.dumps(
            {
                "plan_id": str(plan_id),
                "revision": 1,
                "items": [i.model_dump(mode="json") for i in ready_items],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        reverse_plan = self._repository.create_plan(
            plan_id=plan_id,
            command_run_id=reverse_run.id,
            user_id=user_id,
            revision=1,
            state=CommandState.AWAITING_CONFIRMATION,
            plan_hash=plan_hash,
            canonical_plan_json=canonical,
            expires_at=now + timedelta(minutes=self._plan_expiration_minutes),
            now=now,
        )
        for row, item, _fields in ready_pairs:
            open_links = self._repository.list_open_reversions_for_original_item(row.id)
            if open_links:
                raise UndoInProgressError(
                    f"An open undo plan already exists for item {row.id}"
                )
            if row.reversion_status == ReversionStatus.REVERTED.value:
                raise UndoAlreadyCompletedError(f"Item {row.id} is already reverted")
            self._repository.add_planned_item(plan_id=reverse_plan.id, item=item)
            self._repository.create_item_reversion(
                user_id=user_id,
                original_planned_item_id=row.id,
                original_command_run_id=original_run.id,
                reverse_command_run_id=reverse_run.id,
                reverse_planned_item_id=str(item.item_id),
                state=ReversionLinkState.PLANNED,
                now=now,
            )
            self._repository.set_item_reversion_status(
                row,
                status=ReversionStatus.UNDO_PLANNED,
            )

        self._repository._session.commit()


        def _aware(value: datetime) -> datetime:
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)

        view = ChangePlanView(
            plan_id=UUID(reverse_plan.id),
            revision=reverse_plan.revision,
            state=CommandState(reverse_plan.state),
            original_text=reverse_run.original_text,
            expires_at=_aware(reverse_plan.expires_at),
            confirmed_at=None,
            plan_hash=reverse_plan.plan_hash,
            confirmation_required=True,
            confirmable=True,
            applyable=False,
            items=ready_items,
            apply_results=[],
            created_at=_aware(reverse_plan.created_at),
        )

        ready_count = sum(
            1 for p in previews if p.outcome is UndoItemOutcomeKind.READY
        )
        conflict_count = sum(
            1 for p in previews if p.outcome is UndoItemOutcomeKind.CONFLICT
        )
        skipped_count = len(previews) - ready_count - conflict_count
        return UndoPlanResponse(
            original_command_id=UUID(original_run.id),
            reverse_command_id=UUID(reverse_run.id),
            reverse_plan=view,
            items=previews,
            ready_count=ready_count,
            conflict_count=conflict_count,
            skipped_count=skipped_count,
        )

    async def _evaluate_item(self, row: PlannedItem) -> UndoItemPreview:
        base = UndoItemPreview(
            original_item_id=UUID(row.id),
            outcome=UndoItemOutcomeKind.NOT_REVERSIBLE,
            mal_id=row.mal_id,
            media_type=MediaType(row.media_type) if row.media_type else None,
            canonical_title=row.canonical_title,
        )
        if row.apply_result_kind != ApplyResultKind.VERIFIED.value:
            base.outcome = UndoItemOutcomeKind.NOT_REVERSIBLE
            base.reason = "source_not_verified"
            return base
        if row.is_noop or row.outcome_kind != PlannedItemOutcomeKind.READY.value:
            base.reason = "not_a_verified_write"
            return base
        if not row.before_json or not row.after_json:
            base.reason = "missing_before_after"
            return base
        if row.reversion_status == ReversionStatus.REVERTED.value:
            base.outcome = UndoItemOutcomeKind.ALREADY_REVERTED
            base.reason = "already_reverted"
            return base
        open_links = self._repository.list_open_reversions_for_original_item(row.id)
        if open_links:
            base.outcome = UndoItemOutcomeKind.NOT_REVERSIBLE
            base.reason = "undo_in_progress"
            return base

        before = CurrentListState.model_validate_json(row.before_json)
        after = ProposedListState.model_validate_json(row.after_json)
        base.planned_before = before
        # Verified after is the proposed snapshot for labeling (historical).
        verified_after = CurrentListState(
            media_type=after.media_type,
            is_on_list=True,
            status=after.status,
            score=after.score,
            episode_progress=after.episode_progress,
            chapter_progress=after.chapter_progress,
            volume_progress=after.volume_progress,
        )
        base.verified_after = verified_after

        if not before.is_on_list:
            base.outcome = UndoItemOutcomeKind.NOT_REVERSIBLE
            base.reason = "requires_entry_removal"
            self._repository.set_item_reversion_status(
                row,
                status=ReversionStatus.NOT_REVERSIBLE,
            )
            return base

        changed = changed_fields(before, after)
        if not changed:
            base.reason = "no_changed_fields"
            return base
        base.changed_fields = changed

        if row.mal_id is None or row.media_type is None:
            base.reason = "missing_mal_identity"
            return base

        try:
            observed = await self._read_current(
                MediaType(row.media_type),
                row.mal_id,
            )
        except MalError as exc:
            base.outcome = UndoItemOutcomeKind.LOOKUP_FAILED
            base.reason = exc.error_code
            return base

        base.undo_check_observed = observed
        if not observed.is_on_list:
            base.outcome = UndoItemOutcomeKind.LOOKUP_FAILED
            base.reason = "entry_missing"
            return base

        conflicts = same_field_conflicts(after, observed, changed)
        if conflicts:
            base.outcome = UndoItemOutcomeKind.CONFLICT
            base.conflict_fields = conflicts
            base.reason = "same_field_external_change"
            self._repository.set_item_reversion_status(
                row,
                status=ReversionStatus.REVERSION_CONFLICT,
            )
            return base

        restore = build_field_level_restore(
            current=observed,
            original_before=before,
            changed=changed,
        )
        base.outcome = UndoItemOutcomeKind.READY
        base.proposed_restore = restore
        return base

    async def _read_current(
        self,
        media_type: MediaType,
        mal_id: int,
    ) -> CurrentListState:
        if media_type is MediaType.ANIME:
            anime_entry = await self._mal.get_anime_list_entry(mal_id)
            return list_entry_or_none_to_current_state(media_type, anime_entry)
        manga_entry = await self._mal.get_manga_list_entry(mal_id)
        return list_entry_or_none_to_current_state(media_type, manga_entry)

    def mark_reversions_after_apply(
        self,
        *,
        reverse_plan_id: str,
        now: Any,
    ) -> None:
        """Update reversion links when a reverse plan finishes applying."""
        from datetime import datetime

        assert isinstance(now, datetime)
        reverse_plan = self._repository.get_plan(UUID(reverse_plan_id))
        if reverse_plan is None:
            return
        reverse_run = self._repository.get_command_run(reverse_plan.command_run_id)
        if reverse_run is None or reverse_run.parent_command_id is None:
            return
        reversions = self._repository.list_reversions_for_command(reverse_run.id)
        for link in reversions:
            if link.state != ReversionLinkState.PLANNED.value:
                continue
            reverse_item = self._repository.get_planned_item(
                link.reverse_planned_item_id
            )
            original = self._repository.get_planned_item(
                link.original_planned_item_id
            )
            if reverse_item is None or original is None:
                continue
            if reverse_item.apply_result_kind == ApplyResultKind.VERIFIED.value:
                self._repository.mark_reversion_verified(
                    link,
                    now=now,
                    fully_restored=True,
                )
                self._repository.set_item_reversion_status(
                    original,
                    status=ReversionStatus.REVERTED,
                )
            elif reverse_item.apply_result_kind in (
                ApplyResultKind.STALE_CONFLICT.value,
                ApplyResultKind.VERIFICATION_MISMATCH.value,
            ):
                link.state = ReversionLinkState.CONFLICT.value
                self._repository.set_item_reversion_status(
                    original,
                    status=ReversionStatus.REVERSION_CONFLICT,
                )
                self._repository._session.flush()

        # If all originally verified items are reverted, mark original command.
        original_plan = self._repository.get_plan_by_command_run(
            reverse_run.parent_command_id
        )
        if original_plan is None:
            return
        original_items = self._repository.list_items(original_plan.id)
        verified_originals = [
            i
            for i in original_items
            if i.apply_result_kind == ApplyResultKind.VERIFIED.value
            and i.outcome_kind == PlannedItemOutcomeKind.READY.value
            and not i.is_noop
        ]
        if verified_originals and all(
            i.reversion_status == ReversionStatus.REVERTED.value
            for i in verified_originals
        ):
            if original_plan.state in (
                CommandState.VERIFIED.value,
                CommandState.PARTIALLY_APPLIED.value,
            ):
                validate_transition(
                    CommandState(original_plan.state),
                    CommandState.REVERTED,
                )
                self._repository.set_plan_state(
                    original_plan,
                    state=CommandState.REVERTED,
                    now=now,
                )
            original_run = self._repository.get_command_run(
                reverse_run.parent_command_id
            )
            if original_run is not None and original_run.state in (
                CommandState.VERIFIED.value,
                CommandState.PARTIALLY_APPLIED.value,
            ):
                validate_transition(
                    CommandState(original_run.state),
                    CommandState.REVERTED,
                )
                self._repository.update_command_run_state(
                    original_run,
                    state=CommandState.REVERTED,
                    now=now,
                )


def changed_fields(before: CurrentListState, after: ProposedListState) -> list[str]:
    """Return field names that differ between before and proposed after."""
    result: list[str] = []
    for field in _MUTABLE_FIELDS:
        if getattr(before, field) != getattr(after, field):
            result.append(field)
    return result


def same_field_conflicts(
    original_after: ProposedListState,
    current: CurrentListState,
    changed: list[str],
) -> list[str]:
    """Fields originally changed that no longer match the verified after-state."""
    conflicts: list[str] = []
    for field in changed:
        if getattr(current, field) != getattr(original_after, field):
            conflicts.append(field)
    return conflicts


def build_field_level_restore(
    *,
    current: CurrentListState,
    original_before: CurrentListState,
    changed: list[str],
) -> ProposedListState:
    """Restore only originally changed fields; preserve unrelated current values."""
    data = {
        "media_type": current.media_type,
        "status": current.status,
        "score": current.score,
        "episode_progress": current.episode_progress,
        "chapter_progress": current.chapter_progress,
        "volume_progress": current.volume_progress,
    }
    for field in changed:
        data[field] = getattr(original_before, field)
    return ProposedListState.model_validate(data)


def _requested_from_restore(
    *,
    title: str,
    media_type: MediaType,
    restore: ProposedListState,
    changed_fields: list[str],
) -> RequestedChange:
    """Build a RequestedChange for audit; apply uses planned after snapshot."""
    kwargs: dict[str, Any] = {
        "title": title,
        "media_type": media_type,
    }
    if restore.status is not None:
        kwargs["status"] = restore.status
    if "score" in changed_fields and restore.score is not None:
        kwargs["score"] = restore.score
    if "episode_progress" in changed_fields and restore.episode_progress is not None:
        kwargs["episode_progress"] = restore.episode_progress
    if "chapter_progress" in changed_fields and restore.chapter_progress is not None:
        kwargs["chapter_progress"] = restore.chapter_progress
    if "volume_progress" in changed_fields and restore.volume_progress is not None:
        kwargs["volume_progress"] = restore.volume_progress
    # Ensure at least one mutable field for RequestedChange validation.
    if not any(
        kwargs.get(k) is not None
        for k in (
            "status",
            "score",
            "episode_progress",
            "chapter_progress",
            "volume_progress",
        )
    ):
        if restore.episode_progress is not None:
            kwargs["episode_progress"] = restore.episode_progress
        elif restore.chapter_progress is not None:
            kwargs["chapter_progress"] = restore.chapter_progress
        elif restore.score is not None:
            kwargs["score"] = restore.score
        elif restore.status is not None:
            kwargs["status"] = restore.status
        else:
            # Score/progress clear with no other fields: keep status if present on
            # current entry path — callers should have status. Last resort: 0 eps.
            if media_type is MediaType.ANIME:
                kwargs["episode_progress"] = 0
            else:
                kwargs["chapter_progress"] = 0
    return RequestedChange.model_validate(kwargs)


def _select_items(
    items: list[PlannedItem],
    item_ids: list[UUID] | None,
) -> list[PlannedItem]:
    if item_ids is None:
        return [
            i
            for i in items
            if i.apply_result_kind == ApplyResultKind.VERIFIED.value
        ]
    wanted = {str(i) for i in item_ids}
    selected = [i for i in items if i.id in wanted]
    missing = wanted - {i.id for i in selected}
    if missing:
        raise UndoTargetMissingError(
            f"Planned item(s) not found: {', '.join(sorted(missing))}"
        )
    return selected
