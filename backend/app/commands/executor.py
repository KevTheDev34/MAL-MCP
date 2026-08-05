"""Deterministic change-plan executor with read-after-write verification."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, timedelta
from uuid import UUID

from backend.app.commands.audit import (
    dump_sanitized_json,
    sanitize_error_message,
    sanitize_request_payload,
)
from backend.app.commands.errors import (
    AttemptAlreadyInProgressError,
    PlanCanceledError,
    PlanConcurrencyError,
    PlanExpiredError,
    PlanNotApplyableError,
    PlanNotFoundError,
    PlanOwnershipError,
    PlanRevisionMismatchError,
)
from backend.app.commands.idempotency import build_apply_idempotency_key
from backend.app.commands.models import AppliedItemResult, ApplyPlanResponse
from backend.app.commands.verify import (
    states_equal_for_stale_check,
    verify_proposed_against_remote,
)
from backend.app.db.models import ApplicationAttempt, PlannedItem
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.domain.enums import (
    ApplicationAttemptState,
    ApplyResultKind,
    CommandState,
    MediaType,
    OutcomeCertainty,
    PlannedItemOutcomeKind,
)
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.domain.transitions import validate_transition
from backend.app.mal.client import MalClient
from backend.app.mal.domain_mapping import (
    list_entry_or_none_to_current_state,
    proposed_anime_state_to_update,
    proposed_manga_state_to_update,
)
from backend.app.mal.errors import (
    MalAuthenticationError,
    MalError,
    MalTemporaryError,
    MalValidationError,
)
from backend.app.services.clock import Clock

_APPLY_LOCKS: dict[str, asyncio.Lock] = {}


class ChangePlanExecutor:
    """Apply a confirmed stored plan; never accepts replacement payloads."""

    def __init__(
        self,
        *,
        repository: CommandPlanRepository,
        mal_client: MalClient,
        clock: Clock,
        apply_claim_stale_seconds: int = 120,
        undo_service: object | None = None,
    ) -> None:
        self._repository = repository
        self._mal = mal_client
        self._clock = clock
        self._stale_seconds = apply_claim_stale_seconds
        self._undo_service = undo_service

    async def apply(
        self,
        *,
        user_id: str,
        plan_id: UUID,
        revision: int,
    ) -> ApplyPlanResponse:
        plan = self._repository.get_plan(plan_id)
        if plan is None:
            raise PlanNotFoundError(f"Plan {plan_id} was not found")
        if plan.user_id != user_id:
            raise PlanOwnershipError("Plan does not belong to the authenticated user")
        if plan.revision != revision:
            raise PlanRevisionMismatchError(
                f"Plan revision mismatch: expected {plan.revision}, got {revision}"
            )
        if plan.state == CommandState.REJECTED.value:
            raise PlanCanceledError("Canceled plans cannot be applied")

        if plan.state in (
            CommandState.VERIFIED.value,
            CommandState.PARTIALLY_APPLIED.value,
            CommandState.REVERTED.value,
        ):
            rows = self._repository.list_items(plan.id)
            results = self._repository.build_apply_results(rows)
            return ApplyPlanResponse(
                plan_id=plan_id,
                revision=plan.revision,
                state=CommandState(plan.state),
                already_applied=True,
                requires_new_plan=False,
                results=results,
                counts=_count_results(results),
            )

        if (
            plan.state == CommandState.FAILED.value
            and plan.apply_completed_at is not None
        ):
            rows = self._repository.list_items(plan.id)
            results = self._repository.build_apply_results(rows)
            return ApplyPlanResponse(
                plan_id=plan_id,
                revision=plan.revision,
                state=CommandState.FAILED,
                already_applied=True,
                requires_new_plan=True,
                results=results,
                counts=_count_results(results),
            )

        now = self._clock.now()

        if plan.state == CommandState.APPLYING.value:
            return await self._continue_apply(plan_id=plan_id, user_id=user_id)

        if (
            plan.state != CommandState.AWAITING_CONFIRMATION.value
            or plan.confirmed_at is None
        ):
            raise PlanNotApplyableError(
                f"Plan state {plan.state!r} is not applyable"
            )
        expires_at = plan.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            raise PlanExpiredError("Plan has expired and cannot be applied")

        lock = _APPLY_LOCKS.setdefault(str(plan_id), asyncio.Lock())
        if lock.locked():
            raise PlanConcurrencyError("Plan is already being applied")

        async with lock:
            claimed = self._repository.claim_for_apply(
                plan_id=plan_id,
                revision=revision,
                now=self._clock.now(),
            )
            if claimed is None:
                raise PlanConcurrencyError(
                    "Plan could not be claimed for application"
                )
            run = self._repository.get_command_run(claimed.command_run_id)
            if run is not None:
                current = CommandState(run.state)
                if current is not CommandState.APPLYING:
                    validate_transition(current, CommandState.APPLYING)
                    self._repository.update_command_run_state(
                        run,
                        state=CommandState.APPLYING,
                        now=self._clock.now(),
                    )
            self._repository._session.commit()
            return await self._execute_items(plan_id=plan_id)

    async def _continue_apply(
        self, *, plan_id: UUID, user_id: str
    ) -> ApplyPlanResponse:
        plan = self._repository.get_plan(plan_id)
        assert plan is not None
        if plan.user_id != user_id:
            raise PlanOwnershipError("Plan does not belong to the authenticated user")

        now = self._clock.now()
        if plan.apply_started_at is not None:
            started = plan.apply_started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            # Block only when a non-stale writing attempt exists.
            for row in self._repository.list_items(plan.id):
                attempts = self._repository.list_attempts_for_item(row.id)
                if not attempts:
                    continue
                latest = attempts[-1]
                if latest.state != ApplicationAttemptState.WRITING.value:
                    continue
                attempt_started = latest.started_at
                if attempt_started.tzinfo is None:
                    attempt_started = attempt_started.replace(tzinfo=UTC)
                if (now - attempt_started) < timedelta(seconds=self._stale_seconds):
                    raise AttemptAlreadyInProgressError(
                        "Application attempt is still in progress"
                    )

        lock = _APPLY_LOCKS.setdefault(str(plan_id), asyncio.Lock())
        async with lock:
            return await self._execute_items(plan_id=plan_id)

    async def _execute_items(self, *, plan_id: UUID) -> ApplyPlanResponse:
        plan = self._repository.get_plan(plan_id)
        assert plan is not None
        rows = self._repository.list_items(plan.id)
        results: list[AppliedItemResult] = []
        stop_remaining = False

        for row in sorted(rows, key=lambda r: r.apply_order):
            if row.apply_result_kind == ApplyResultKind.VERIFIED.value:
                results.append(
                    AppliedItemResult(
                        item_id=UUID(row.id),
                        apply_order=row.apply_order,
                        result=ApplyResultKind.VERIFIED,
                        mal_id=row.mal_id,
                        media_type=(
                            MediaType(row.media_type) if row.media_type else None
                        ),
                        canonical_title=row.canonical_title,
                    )
                )
                continue

            if stop_remaining:
                result = self._skip_item(row, ApplyResultKind.SKIPPED_AUTH_STOP)
                results.append(result)
                continue

            kind = PlannedItemOutcomeKind(row.outcome_kind)
            if kind is PlannedItemOutcomeKind.NOOP:
                results.append(self._skip_item(row, ApplyResultKind.SKIPPED_NOOP))
                continue
            if kind in (
                PlannedItemOutcomeKind.AMBIGUOUS,
                PlannedItemOutcomeKind.NOT_FOUND,
                PlannedItemOutcomeKind.LOOKUP_FAILED,
            ):
                results.append(
                    self._skip_item(row, ApplyResultKind.SKIPPED_UNRESOLVED)
                )
                continue
            if kind is PlannedItemOutcomeKind.INVALID:
                results.append(self._skip_item(row, ApplyResultKind.SKIPPED_INVALID))
                continue
            if kind is not PlannedItemOutcomeKind.READY:
                results.append(self._skip_item(row, ApplyResultKind.NOT_ATTEMPTED))
                continue

            attempts = self._repository.list_attempts_for_item(row.id)
            if attempts:
                latest = attempts[-1]
                if latest.state in (
                    ApplicationAttemptState.WRITING.value,
                    ApplicationAttemptState.WRITTEN_UNVERIFIED.value,
                ):
                    recovered = await self._recover_interrupted(row, latest)
                    results.append(recovered)
                    if recovered.result is ApplyResultKind.AUTHENTICATION_FAILURE:
                        stop_remaining = True
                    continue

            item_result = await self._apply_ready_item(row, plan)
            results.append(item_result)
            if item_result.result is ApplyResultKind.AUTHENTICATION_FAILURE:
                stop_remaining = True

        overall = _overall_state(results)
        now = self._clock.now()
        plan = self._repository.get_plan(plan_id)
        assert plan is not None
        self._repository.set_plan_state(
            plan,
            state=overall,
            now=now,
            apply_completed=True,
        )
        run = self._repository.get_command_run(plan.command_run_id)
        if run is not None:
            self._repository.update_command_run_state(run, state=overall, now=now)

        if self._undo_service is not None:
            marker = getattr(self._undo_service, "mark_reversions_after_apply", None)
            if callable(marker):
                marker(reverse_plan_id=plan.id, now=now)

        self._repository._session.commit()

        requires_new = any(
            r.result
            in (
                ApplyResultKind.STALE_CONFLICT,
                ApplyResultKind.VERIFICATION_MISMATCH,
                ApplyResultKind.MAL_VALIDATION_FAILURE,
                ApplyResultKind.TEMPORARY_FAILURE,
                ApplyResultKind.VERIFICATION_UNKNOWN,
            )
            for r in results
        )
        return ApplyPlanResponse(
            plan_id=plan_id,
            revision=plan.revision,
            state=overall,
            already_applied=False,
            requires_new_plan=requires_new,
            results=results,
            counts=_count_results(results),
        )

    def _skip_item(
        self,
        row: PlannedItem,
        result: ApplyResultKind,
    ) -> AppliedItemResult:
        self._repository.set_item_apply_result(row, result=result)
        return AppliedItemResult(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            result=result,
            mal_id=row.mal_id,
            media_type=MediaType(row.media_type) if row.media_type else None,
            canonical_title=row.canonical_title,
        )

    async def _apply_ready_item(
        self,
        row: PlannedItem,
        plan: object,
    ) -> AppliedItemResult:
        from backend.app.db.models import ChangePlanRecord

        assert isinstance(plan, ChangePlanRecord)
        assert row.before_json and row.after_json and row.media_type and row.mal_id
        before = CurrentListState.model_validate_json(row.before_json)
        after = ProposedListState.model_validate_json(row.after_json)
        media_type = MediaType(row.media_type)
        now = self._clock.now()

        key = build_apply_idempotency_key(
            user_id=plan.user_id,
            plan_id=plan.id,
            revision=plan.revision,
            planned_item_id=row.id,
            plan_hash=plan.plan_hash,
        )
        existing = self._repository.get_attempt_by_idempotency_key(key)
        if existing is not None:
            if existing.state == ApplicationAttemptState.VERIFIED.value:
                verified = None
                if existing.verified_state_json:
                    verified = CurrentListState.model_validate_json(
                        existing.verified_state_json
                    )
                return AppliedItemResult(
                    item_id=UUID(row.id),
                    apply_order=row.apply_order,
                    result=ApplyResultKind.VERIFIED,
                    mal_id=row.mal_id,
                    media_type=media_type,
                    canonical_title=row.canonical_title,
                    verified_state=verified,
                )
            if existing.state in (
                ApplicationAttemptState.WRITING.value,
                ApplicationAttemptState.WRITTEN_UNVERIFIED.value,
            ):
                return await self._recover_interrupted(row, existing)

        attempt = self._repository.create_attempt(
            planned_item_id=row.id,
            attempt_number=len(self._repository.list_attempts_for_item(row.id)) + 1,
            state=ApplicationAttemptState.WRITING,
            now=now,
            idempotency_key=key,
            outcome_certainty=OutcomeCertainty.UNCERTAIN,
        )
        self._repository._session.commit()

        try:
            observed = await self._read_current(media_type, row.mal_id)
        except MalAuthenticationError as exc:
            return self._fail_attempt(
                row,
                attempt,
                result=ApplyResultKind.AUTHENTICATION_FAILURE,
                attempt_state=ApplicationAttemptState.FAILED,
                error_type=exc.error_code,
                error_message=exc.message,
            )
        except MalError as exc:
            return self._fail_attempt(
                row,
                attempt,
                result=ApplyResultKind.TEMPORARY_FAILURE,
                attempt_state=ApplicationAttemptState.FAILED,
                error_type=exc.error_code,
                error_message=exc.message,
            )

        if not states_equal_for_stale_check(before, observed):
            self._repository.finish_attempt(
                attempt,
                state=ApplicationAttemptState.CONFLICT,
                now=self._clock.now(),
                observed_state_json=observed.model_dump_json(),
                error_type="stale_conflict",
                error_message_redacted=sanitize_error_message(
                    "Current MAL state differs from planned before-state"
                ),
                outcome_certainty=OutcomeCertainty.CERTAIN,
            )
            self._repository.set_item_apply_result(
                row,
                result=ApplyResultKind.STALE_CONFLICT,
            )
            self._repository._session.commit()
            return AppliedItemResult(
                item_id=UUID(row.id),
                apply_order=row.apply_order,
                result=ApplyResultKind.STALE_CONFLICT,
                mal_id=row.mal_id,
                media_type=media_type,
                canonical_title=row.canonical_title,
                observed_state=observed,
                error_code="stale_conflict",
                error_message="Current MAL state differs from planned before-state",
            )

        try:
            if media_type is MediaType.ANIME:
                anime_update = proposed_anime_state_to_update(
                    before=before,
                    after=after,
                )
                sanitized = sanitize_request_payload(
                    anime_update.model_dump(exclude_none=True)
                )
                attempt.request_json = dump_sanitized_json(sanitized or {})
                self._repository._session.flush()
                await self._mal.update_anime_list_entry(row.mal_id, anime_update)
            else:
                manga_update = proposed_manga_state_to_update(
                    before=before,
                    after=after,
                )
                sanitized = sanitize_request_payload(
                    manga_update.model_dump(exclude_none=True)
                )
                attempt.request_json = dump_sanitized_json(sanitized or {})
                self._repository._session.flush()
                await self._mal.update_manga_list_entry(row.mal_id, manga_update)
        except MalAuthenticationError as exc:
            return self._fail_attempt(
                row,
                attempt,
                result=ApplyResultKind.AUTHENTICATION_FAILURE,
                attempt_state=ApplicationAttemptState.FAILED,
                error_type=exc.error_code,
                error_message=exc.message,
            )
        except MalValidationError as exc:
            return self._fail_attempt(
                row,
                attempt,
                result=ApplyResultKind.MAL_VALIDATION_FAILURE,
                attempt_state=ApplicationAttemptState.FAILED,
                error_type=exc.error_code,
                error_message=exc.message,
            )
        except MalTemporaryError as exc:
            # Uncertain: request may have been accepted.
            self._repository.finish_attempt(
                attempt,
                state=ApplicationAttemptState.WRITTEN_UNVERIFIED,
                now=self._clock.now(),
                error_type=exc.error_code,
                error_message_redacted=sanitize_error_message(exc.message),
                outcome_certainty=OutcomeCertainty.UNCERTAIN,
            )
            self._repository.set_item_apply_result(
                row,
                result=ApplyResultKind.VERIFICATION_UNKNOWN,
            )
            self._repository._session.commit()
            return AppliedItemResult(
                item_id=UUID(row.id),
                apply_order=row.apply_order,
                result=ApplyResultKind.VERIFICATION_UNKNOWN,
                mal_id=row.mal_id,
                media_type=media_type,
                canonical_title=row.canonical_title,
                error_code=exc.error_code,
                error_message=exc.message,
            )
        except MalError as exc:
            return self._fail_attempt(
                row,
                attempt,
                result=ApplyResultKind.TEMPORARY_FAILURE,
                attempt_state=ApplicationAttemptState.FAILED,
                error_type=exc.error_code,
                error_message=exc.message,
            )

        self._repository.finish_attempt(
            attempt,
            state=ApplicationAttemptState.WRITTEN_UNVERIFIED,
            now=self._clock.now(),
            update_response_json=dump_sanitized_json({"status": "accepted"}),
            outcome_certainty=OutcomeCertainty.UNCERTAIN,
        )
        self._repository._session.commit()

        return await self._verify_after_write(row, attempt, after, media_type)

    async def _recover_interrupted(
        self,
        row: PlannedItem,
        attempt: ApplicationAttempt,
    ) -> AppliedItemResult:
        """Classify writing / written_unverified without issuing another write."""
        assert row.before_json and row.after_json and row.media_type and row.mal_id
        before = CurrentListState.model_validate_json(row.before_json)
        after = ProposedListState.model_validate_json(row.after_json)
        media_type = MediaType(row.media_type)
        try:
            observed = await self._read_current(media_type, row.mal_id)
        except MalAuthenticationError as exc:
            return self._fail_attempt(
                row,
                attempt,
                result=ApplyResultKind.AUTHENTICATION_FAILURE,
                attempt_state=ApplicationAttemptState.FAILED,
                error_type=exc.error_code,
                error_message=exc.message,
                certainty=OutcomeCertainty.UNCERTAIN,
            )
        except MalError as exc:
            return self._fail_attempt(
                row,
                attempt,
                result=ApplyResultKind.VERIFICATION_UNKNOWN,
                attempt_state=ApplicationAttemptState.FAILED,
                error_type=exc.error_code,
                error_message=exc.message,
                certainty=OutcomeCertainty.UNCERTAIN,
            )

        verification = verify_proposed_against_remote(
            intended=after,
            remote=observed,
            media_type=media_type,
        )
        if verification.kind == "verified":
            self._repository.finish_attempt(
                attempt,
                state=ApplicationAttemptState.VERIFIED,
                now=self._clock.now(),
                verified_state_json=observed.model_dump_json(),
                observed_state_json=observed.model_dump_json(),
                outcome_certainty=OutcomeCertainty.RECOVERED,
            )
            self._repository.set_item_apply_result(row, result=ApplyResultKind.VERIFIED)
            self._repository._session.commit()
            return AppliedItemResult(
                item_id=UUID(row.id),
                apply_order=row.apply_order,
                result=ApplyResultKind.VERIFIED,
                mal_id=row.mal_id,
                media_type=media_type,
                canonical_title=row.canonical_title,
                verified_state=observed,
            )

        if states_equal_for_stale_check(before, observed):
            self._repository.finish_attempt(
                attempt,
                state=ApplicationAttemptState.FAILED,
                now=self._clock.now(),
                observed_state_json=observed.model_dump_json(),
                error_type="failed_before_write",
                error_message_redacted=sanitize_error_message(
                    "Remote state still matches planned before-state"
                ),
                outcome_certainty=OutcomeCertainty.CERTAIN,
            )
            self._repository.set_item_apply_result(
                row,
                result=ApplyResultKind.TEMPORARY_FAILURE,
            )
            self._repository._session.commit()
            return AppliedItemResult(
                item_id=UUID(row.id),
                apply_order=row.apply_order,
                result=ApplyResultKind.TEMPORARY_FAILURE,
                mal_id=row.mal_id,
                media_type=media_type,
                canonical_title=row.canonical_title,
                observed_state=observed,
                error_code="failed_before_write",
                error_message="Remote state still matches planned before-state",
            )

        self._repository.finish_attempt(
            attempt,
            state=ApplicationAttemptState.CONFLICT,
            now=self._clock.now(),
            observed_state_json=observed.model_dump_json(),
            error_type="verification_unknown",
            error_message_redacted=sanitize_error_message(
                verification.message
                or "Unverified write does not match intended state"
            ),
            outcome_certainty=OutcomeCertainty.CERTAIN,
            field_mismatches_json=json.dumps(verification.field_mismatches),
        )
        self._repository.set_item_apply_result(
            row,
            result=ApplyResultKind.VERIFICATION_UNKNOWN,
        )
        self._repository._session.commit()
        return AppliedItemResult(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            result=ApplyResultKind.VERIFICATION_UNKNOWN,
            mal_id=row.mal_id,
            media_type=media_type,
            canonical_title=row.canonical_title,
            observed_state=observed,
            error_code="verification_unknown",
            error_message=verification.message,
            field_mismatches=verification.field_mismatches,
        )

    async def _verify_after_write(
        self,
        row: PlannedItem,
        attempt: ApplicationAttempt,
        after: ProposedListState,
        media_type: MediaType,
    ) -> AppliedItemResult:
        assert row.mal_id is not None
        try:
            remote = await self._read_current(media_type, row.mal_id)
        except MalError as exc:
            self._repository.finish_attempt(
                attempt,
                state=ApplicationAttemptState.FAILED,
                now=self._clock.now(),
                error_type=exc.error_code,
                error_message_redacted=sanitize_error_message(exc.message),
                outcome_certainty=OutcomeCertainty.UNCERTAIN,
            )
            self._repository.set_item_apply_result(
                row,
                result=ApplyResultKind.VERIFICATION_UNKNOWN,
            )
            self._repository._session.commit()
            return AppliedItemResult(
                item_id=UUID(row.id),
                apply_order=row.apply_order,
                result=ApplyResultKind.VERIFICATION_UNKNOWN,
                mal_id=row.mal_id,
                media_type=media_type,
                canonical_title=row.canonical_title,
                error_code=exc.error_code,
                error_message=exc.message,
            )

        verification = verify_proposed_against_remote(
            intended=after,
            remote=remote,
            media_type=media_type,
        )
        if verification.kind == "verified":
            self._repository.finish_attempt(
                attempt,
                state=ApplicationAttemptState.VERIFIED,
                now=self._clock.now(),
                verified_state_json=remote.model_dump_json() if remote else None,
                outcome_certainty=OutcomeCertainty.CERTAIN,
            )
            self._repository.set_item_apply_result(row, result=ApplyResultKind.VERIFIED)
            self._repository._session.commit()
            return AppliedItemResult(
                item_id=UUID(row.id),
                apply_order=row.apply_order,
                result=ApplyResultKind.VERIFIED,
                mal_id=row.mal_id,
                media_type=media_type,
                canonical_title=row.canonical_title,
                verified_state=remote,
            )

        result_kind = (
            ApplyResultKind.VERIFICATION_MISMATCH
            if verification.kind == "mismatch"
            else ApplyResultKind.VERIFICATION_UNKNOWN
        )
        self._repository.finish_attempt(
            attempt,
            state=ApplicationAttemptState.FAILED,
            now=self._clock.now(),
            verified_state_json=remote.model_dump_json() if remote else None,
            error_type=verification.kind,
            error_message_redacted=sanitize_error_message(verification.message),
            outcome_certainty=OutcomeCertainty.CERTAIN,
            field_mismatches_json=json.dumps(verification.field_mismatches),
        )
        self._repository.set_item_apply_result(row, result=result_kind)
        self._repository._session.commit()
        return AppliedItemResult(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            result=result_kind,
            mal_id=row.mal_id,
            media_type=media_type,
            canonical_title=row.canonical_title,
            verified_state=remote,
            error_code=verification.kind,
            error_message=verification.message,
            field_mismatches=verification.field_mismatches,
        )

    def _fail_attempt(
        self,
        row: PlannedItem,
        attempt: ApplicationAttempt,
        *,
        result: ApplyResultKind,
        attempt_state: ApplicationAttemptState,
        error_type: str,
        error_message: str,
        certainty: OutcomeCertainty = OutcomeCertainty.CERTAIN,
    ) -> AppliedItemResult:
        self._repository.finish_attempt(
            attempt,
            state=attempt_state,
            now=self._clock.now(),
            error_type=error_type,
            error_message_redacted=sanitize_error_message(error_message),
            outcome_certainty=certainty,
        )
        self._repository.set_item_apply_result(row, result=result)
        self._repository._session.commit()
        return AppliedItemResult(
            item_id=UUID(row.id),
            apply_order=row.apply_order,
            result=result,
            mal_id=row.mal_id,
            media_type=MediaType(row.media_type) if row.media_type else None,
            canonical_title=row.canonical_title,
            error_code=error_type,
            error_message=error_message,
        )

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


def _overall_state(results: list[AppliedItemResult]) -> CommandState:
    ready_results = [
        r
        for r in results
        if r.result
        not in (
            ApplyResultKind.SKIPPED_NOOP,
            ApplyResultKind.SKIPPED_UNRESOLVED,
            ApplyResultKind.SKIPPED_INVALID,
            ApplyResultKind.NOT_ATTEMPTED,
        )
    ]
    if not ready_results:
        return CommandState.VERIFIED
    verified = [r for r in ready_results if r.result is ApplyResultKind.VERIFIED]
    if len(verified) == len(ready_results):
        return CommandState.VERIFIED
    if not verified:
        return CommandState.FAILED
    return CommandState.PARTIALLY_APPLIED


def _count_results(results: list[AppliedItemResult]) -> dict[str, int]:
    counter = Counter(r.result.value for r in results)
    return dict(counter)
