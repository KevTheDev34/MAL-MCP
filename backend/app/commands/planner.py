"""Deterministic change planner — never writes to MAL."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

from backend.app.commands.duplicates import (
    MergeConflict,
    ResolvedRequest,
    merge_resolved_requests,
)
from backend.app.commands.errors import PlanResolveFailedError, PlanValidationError
from backend.app.commands.hashing import compute_plan_hash
from backend.app.commands.models import (
    AmbiguousPlannedItem,
    ChangePlanView,
    InvalidPlannedItem,
    LookupFailedPlannedItem,
    NoOpPlannedItem,
    NotFoundPlannedItem,
    PlannedItemResult,
    ReadyPlannedItem,
)
from backend.app.commands.propose import calculate_proposed_state, is_noop_change
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.domain.enums import (
    CommandState,
    DomainErrorCode,
    PlannedItemOutcomeKind,
)
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.requests import RequestedChange
from backend.app.domain.transitions import validate_transition
from backend.app.mal.client import MalClient
from backend.app.mal.domain_mapping import list_entry_or_none_to_current_state
from backend.app.mal.errors import (
    MalAuthenticationError,
    MalError,
    MalNotFoundError,
    MalRateLimitError,
    MalTemporaryError,
)
from backend.app.resolver.errors import (
    ResolverAuthenticationError,
    ResolverTemporaryError,
    ResolverValidationError,
)
from backend.app.resolver.models import (
    AmbiguousOutcome,
    NotFoundOutcome,
    ResolvedOutcome,
    ResolveTitleRequest,
)
from backend.app.resolver.service import TitleResolver
from backend.app.services.clock import Clock


class ChangePlanner:
    """Build persisted before/after change plans from structured requests."""

    def __init__(
        self,
        *,
        repository: CommandPlanRepository,
        resolver: TitleResolver,
        mal_client: MalClient,
        clock: Clock,
        plan_expiration_minutes: int,
        max_plan_changes: int,
    ) -> None:
        self._repository = repository
        self._resolver = resolver
        self._mal = mal_client
        self._clock = clock
        self._plan_expiration_minutes = plan_expiration_minutes
        self._max_plan_changes = max_plan_changes

    async def create_plan(
        self,
        *,
        user_id: str,
        requested_changes: list[RequestedChange],
        original_text: str | None = None,
    ) -> ChangePlanView:
        if not requested_changes:
            raise PlanValidationError(
                "At least one requested change is required",
                code=DomainErrorCode.EMPTY_PLAN.value,
                field="changes",
            )
        if len(requested_changes) > self._max_plan_changes:
            raise PlanValidationError(
                f"Plan exceeds maximum of {self._max_plan_changes} changes",
                code=DomainErrorCode.PLAN_TOO_LARGE.value,
                field="changes",
            )

        now = self._clock.now()
        request_json = json.dumps(
            [c.model_dump(mode="json") for c in requested_changes],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        run = self._repository.create_command_run(
            user_id=user_id,
            original_text=original_text,
            normalized_request_json=request_json,
            state=CommandState.RECEIVED,
            now=now,
        )
        self._transition_run(run, CommandState.PARSED, now)
        self._transition_run(run, CommandState.RESOLVING, now)

        items: list[PlannedItemResult] = []
        resolved_batch: list[ResolvedRequest] = []
        unresolved: list[PlannedItemResult] = []
        order = 0

        try:
            for requested in requested_changes:
                outcome = await self._resolver.resolve(
                    user_id=user_id,
                    request=ResolveTitleRequest(
                        title=requested.title,
                        media_type=requested.media_type,
                    ),
                )
                if isinstance(outcome, ResolvedOutcome):
                    resolved_batch.append(
                        ResolvedRequest(
                            requested=requested,
                            media=outcome.media,
                            source_titles=[requested.title],
                        )
                    )
                elif isinstance(outcome, AmbiguousOutcome):
                    unresolved.append(
                        AmbiguousPlannedItem(
                            item_id=uuid4(),
                            apply_order=order,
                            requested=requested,
                            source_titles=[requested.title],
                            query=outcome.query,
                            candidates=outcome.candidates,
                            reason=outcome.reason,
                        )
                    )
                    order += 1
                elif isinstance(outcome, NotFoundOutcome):
                    unresolved.append(
                        NotFoundPlannedItem(
                            item_id=uuid4(),
                            apply_order=order,
                            requested=requested,
                            source_titles=[requested.title],
                            query=outcome.query,
                            media_type=outcome.media_type,
                            reason=outcome.reason,
                        )
                    )
                    order += 1
        except ResolverAuthenticationError as exc:
            self._repository.update_command_run_state(
                run,
                state=CommandState.FAILED,
                now=self._clock.now(),
            )
            self._repository._session.commit()
            raise PlanResolveFailedError(exc.message, code=exc.error_code) from exc
        except ResolverTemporaryError as exc:
            self._repository.update_command_run_state(
                run,
                state=CommandState.FAILED,
                now=self._clock.now(),
            )
            self._repository._session.commit()
            raise PlanResolveFailedError(exc.message, code=exc.error_code) from exc
        except ResolverValidationError as exc:
            self._repository.update_command_run_state(
                run,
                state=CommandState.REJECTED,
                now=self._clock.now(),
            )
            self._repository._session.commit()
            raise PlanValidationError(
                exc.message,
                code="resolver_validation_error",
                field=exc.field,
            ) from exc

        merge = merge_resolved_requests(resolved_batch)
        for conflict in merge.conflicts:
            items.append(_conflict_item(conflict, order))
            order += 1

        for resolved in merge.merged:
            item = await self._plan_resolved(resolved, order)
            items.append(item)
            order += 1

        # Preserve unresolved items after merged resolved items, renumber.
        for item in unresolved:
            items.append(item.model_copy(update={"apply_order": order}))
            order += 1

        # Stable apply_order already assigned; sort for determinism.
        items.sort(key=lambda i: i.apply_order)
        for idx, item in enumerate(items):
            items[idx] = item.model_copy(update={"apply_order": idx})

        final_state = _final_plan_state(items)
        if final_state is CommandState.AWAITING_CLARIFICATION:
            self._transition_run(run, CommandState.AWAITING_CLARIFICATION, now)
        else:
            self._transition_run(run, CommandState.PLANNED, now)
            if final_state is CommandState.AWAITING_CONFIRMATION:
                self._transition_run(run, CommandState.AWAITING_CONFIRMATION, now)

        plan_id = uuid4()
        revision = 1
        plan_hash = compute_plan_hash(
            plan_id=plan_id,
            revision=revision,
            user_id=user_id,
            items=items,
        )
        expires_at = now + timedelta(minutes=self._plan_expiration_minutes)
        canonical = json.dumps(
            {
                "plan_id": str(plan_id),
                "revision": revision,
                "items": [i.model_dump(mode="json") for i in items],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        plan = self._repository.create_plan(
            plan_id=plan_id,
            command_run_id=run.id,
            user_id=user_id,
            revision=revision,
            state=final_state,
            plan_hash=plan_hash,
            canonical_plan_json=canonical,
            expires_at=expires_at,
            now=now,
        )
        for item in items:
            self._repository.add_planned_item(plan_id=plan.id, item=item)

        self._repository._session.commit()

        confirmable = any(i.kind is PlannedItemOutcomeKind.READY for i in items)
        return ChangePlanView(
            plan_id=plan_id,
            revision=revision,
            state=final_state,
            original_text=original_text,
            expires_at=expires_at,
            confirmed_at=None,
            plan_hash=plan_hash,
            confirmation_required=confirmable,
            confirmable=confirmable,
            applyable=False,
            items=items,
            created_at=now,
        )

    async def _plan_resolved(
        self,
        resolved: ResolvedRequest,
        order: int,
    ) -> PlannedItemResult:
        media = resolved.media
        requested = resolved.requested
        try:
            if media.media_type.value == "anime":
                anime_entry = await self._mal.get_anime_list_entry(media.mal_id)
                current = list_entry_or_none_to_current_state(
                    media.media_type,
                    anime_entry,
                )
            else:
                manga_entry = await self._mal.get_manga_list_entry(media.mal_id)
                current = list_entry_or_none_to_current_state(
                    media.media_type,
                    manga_entry,
                )
        except MalNotFoundError as exc:
            return InvalidPlannedItem(
                item_id=uuid4(),
                apply_order=order,
                requested=requested,
                source_titles=resolved.source_titles,
                error_code=exc.error_code,
                error_message="Resolved MAL ID was not found when reading list state",
                media=media,
            )
        except (MalAuthenticationError, MalTemporaryError, MalRateLimitError) as exc:
            return LookupFailedPlannedItem(
                item_id=uuid4(),
                apply_order=order,
                requested=requested,
                source_titles=resolved.source_titles,
                media=media,
                error_code=exc.error_code,
                error_message=exc.message,
            )
        except MalError as exc:
            return LookupFailedPlannedItem(
                item_id=uuid4(),
                apply_order=order,
                requested=requested,
                source_titles=resolved.source_titles,
                media=media,
                error_code=exc.error_code,
                error_message=exc.message,
            )

        try:
            after, warnings = calculate_proposed_state(
                requested=requested,
                media=media,
                current=current,
            )
        except DomainValidationError as exc:
            return InvalidPlannedItem(
                item_id=uuid4(),
                apply_order=order,
                requested=requested,
                source_titles=resolved.source_titles,
                error_code=exc.code.value,
                error_message=exc.message,
                media=media,
                before=current,
            )

        if is_noop_change(before=current, after=after):
            return NoOpPlannedItem(
                item_id=uuid4(),
                apply_order=order,
                requested=requested,
                source_titles=resolved.source_titles,
                media=media,
                before=current,
                after=after,
                warnings=warnings,
            )

        return ReadyPlannedItem(
            item_id=uuid4(),
            apply_order=order,
            requested=requested,
            source_titles=resolved.source_titles,
            media=media,
            before=current,
            after=after,
            warnings=warnings,
        )

    def _transition_run(
        self,
        run: object,
        target: CommandState,
        now: object,
    ) -> None:
        from backend.app.db.models import CommandRun

        assert isinstance(run, CommandRun)
        from datetime import datetime

        assert isinstance(now, datetime)
        current = CommandState(run.state)
        validate_transition(current, target)
        self._repository.update_command_run_state(run, state=target, now=now)


def _final_plan_state(items: list[PlannedItemResult]) -> CommandState:
    if any(i.kind is PlannedItemOutcomeKind.READY for i in items):
        return CommandState.AWAITING_CONFIRMATION
    if items and all(
        i.kind
        in (
            PlannedItemOutcomeKind.AMBIGUOUS,
            PlannedItemOutcomeKind.NOT_FOUND,
            PlannedItemOutcomeKind.LOOKUP_FAILED,
        )
        for i in items
    ):
        return CommandState.AWAITING_CLARIFICATION
    return CommandState.PLANNED


def _conflict_item(conflict: MergeConflict, order: int) -> InvalidPlannedItem:
    return InvalidPlannedItem(
        item_id=uuid4(),
        apply_order=order,
        requested=conflict.requests[0],
        source_titles=conflict.source_titles,
        error_code=DomainErrorCode.DUPLICATE_TARGET_CONFLICT.value,
        error_message=conflict.message,
        media=conflict.media,
    )
