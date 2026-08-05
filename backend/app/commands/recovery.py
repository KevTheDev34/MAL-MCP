"""Recover interrupted or uncertain application attempts without blind replay."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID

from backend.app.commands.audit import sanitize_error_message
from backend.app.commands.errors import (
    AttemptAlreadyInProgressError,
    PlanNotFoundError,
    PlanOwnershipError,
    PlanRevisionMismatchError,
    RecoveryNotRequiredError,
)
from backend.app.commands.models import (
    AppliedItemResult,
    RecoveryItemResult,
    RecoveryResult,
)
from backend.app.commands.verify import (
    states_equal_for_stale_check,
    verify_proposed_against_remote,
)
from backend.app.db.models import PlannedItem
from backend.app.db.repositories.command_plans import CommandPlanRepository
from backend.app.domain.enums import (
    ApplicationAttemptState,
    ApplyResultKind,
    CommandState,
    MediaType,
    OutcomeCertainty,
)
from backend.app.domain.state import CurrentListState, ProposedListState
from backend.app.mal.client import MalClient
from backend.app.mal.domain_mapping import list_entry_or_none_to_current_state
from backend.app.mal.errors import MalAuthenticationError, MalError
from backend.app.services.clock import Clock


class ApplicationRecoveryService:
    """Classify interrupted attempts by reading current MAL state."""

    def __init__(
        self,
        *,
        repository: CommandPlanRepository,
        mal_client: MalClient,
        clock: Clock,
        apply_claim_stale_seconds: int = 120,
    ) -> None:
        self._repository = repository
        self._mal = mal_client
        self._clock = clock
        self._stale_seconds = apply_claim_stale_seconds

    async def recover_plan(
        self,
        *,
        user_id: str,
        plan_id: UUID,
        revision: int,
    ) -> RecoveryResult:
        plan = self._repository.get_plan(plan_id)
        if plan is None:
            raise PlanNotFoundError(f"Plan {plan_id} was not found")
        if plan.user_id != user_id:
            raise PlanOwnershipError("Plan does not belong to the authenticated user")
        if plan.revision != revision:
            raise PlanRevisionMismatchError(
                f"Plan revision mismatch: expected {plan.revision}, got {revision}"
            )

        rows = self._repository.list_items(plan.id)
        recoverable = [
            row
            for row in rows
            if self._needs_recovery(row)
        ]
        if not recoverable and plan.state != CommandState.APPLYING.value:
            raise RecoveryNotRequiredError("No interrupted application attempts found")

        now = self._clock.now()
        applying = plan.state == CommandState.APPLYING.value
        if applying and plan.apply_started_at is not None:
            started = plan.apply_started_at
            if started.tzinfo is None:
                from datetime import UTC

                started = started.replace(tzinfo=UTC)
            age = now - started
            if age < timedelta(seconds=self._stale_seconds):
                # Allow recovery of written_unverified even if plan apply is fresh,
                # but block only when a writing attempt is still within the lease.
                writing = any(
                    self._latest_attempt_state(row)
                    == ApplicationAttemptState.WRITING.value
                    and not self._attempt_is_stale(row, now)
                    for row in recoverable
                )
                if writing:
                    raise AttemptAlreadyInProgressError(
                        "Application attempt is still in progress"
                    )

        item_results: list[RecoveryItemResult] = []
        for row in sorted(rows, key=lambda r: r.apply_order):
            if not self._needs_recovery(row):
                continue
            item_results.append(await self._recover_item(row))

        # Recalculate overall plan state from all item apply results.
        all_rows = self._repository.list_items(plan.id)
        apply_results = self._repository.build_apply_results(all_rows)
        overall = _overall_state(apply_results)
        plan = self._repository.get_plan(plan_id)
        assert plan is not None
        if plan.state == CommandState.APPLYING.value and overall in (
            CommandState.VERIFIED,
            CommandState.PARTIALLY_APPLIED,
            CommandState.FAILED,
        ):
            self._repository.set_plan_state(
                plan,
                state=overall,
                now=self._clock.now(),
                apply_completed=True,
            )
            run = self._repository.get_command_run(plan.command_run_id)
            if run is not None:
                self._repository.update_command_run_state(
                    run,
                    state=overall,
                    now=self._clock.now(),
                )
        self._repository._session.commit()

        return RecoveryResult(
            plan_id=plan_id,
            revision=revision,
            state=CommandState(plan.state),
            items=item_results,
            next_action=_next_action(item_results, CommandState(plan.state)),
        )

    def _needs_recovery(self, row: PlannedItem) -> bool:
        attempts = self._repository.list_attempts_for_item(row.id)
        if not attempts:
            return False
        latest = attempts[-1]
        if latest.state in (
            ApplicationAttemptState.WRITING.value,
            ApplicationAttemptState.WRITTEN_UNVERIFIED.value,
        ):
            return True
        if row.apply_result_kind == ApplyResultKind.VERIFICATION_UNKNOWN.value:
            return True
        return latest.outcome_certainty == OutcomeCertainty.UNCERTAIN.value and (
            latest.state
            in (
                ApplicationAttemptState.WRITING.value,
                ApplicationAttemptState.WRITTEN_UNVERIFIED.value,
                ApplicationAttemptState.FAILED.value,
            )
        )

    def _latest_attempt_state(self, row: PlannedItem) -> str | None:
        attempts = self._repository.list_attempts_for_item(row.id)
        if not attempts:
            return None
        return attempts[-1].state

    def _attempt_is_stale(self, row: PlannedItem, now: object) -> bool:
        from datetime import UTC, datetime

        assert isinstance(now, datetime)
        attempts = self._repository.list_attempts_for_item(row.id)
        if not attempts:
            return True
        started = attempts[-1].started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return (now - started) >= timedelta(seconds=self._stale_seconds)

    async def _recover_item(self, row: PlannedItem) -> RecoveryItemResult:
        assert row.before_json and row.after_json and row.media_type and row.mal_id
        before = CurrentListState.model_validate_json(row.before_json)
        after = ProposedListState.model_validate_json(row.after_json)
        media_type = MediaType(row.media_type)
        attempts = self._repository.list_attempts_for_item(row.id)
        attempt = attempts[-1]

        try:
            observed = await self._read_current(media_type, row.mal_id)
        except MalAuthenticationError as exc:
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
                result=ApplyResultKind.AUTHENTICATION_FAILURE,
            )
            self._repository._session.flush()
            return RecoveryItemResult(
                item_id=UUID(row.id),
                classification="remote_lookup_failed",
                apply_result=ApplyResultKind.AUTHENTICATION_FAILURE,
                wrote_again=False,
                message=exc.message,
            )
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
            self._repository._session.flush()
            return RecoveryItemResult(
                item_id=UUID(row.id),
                classification="remote_lookup_failed",
                apply_result=ApplyResultKind.VERIFICATION_UNKNOWN,
                wrote_again=False,
                observed_state=None,
                message=exc.message,
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
            self._repository._session.flush()
            return RecoveryItemResult(
                item_id=UUID(row.id),
                classification="intended_state_present",
                apply_result=ApplyResultKind.VERIFIED,
                wrote_again=False,
                observed_state=observed,
                message=(
                    "Intended state already present; recorded as recovered verified"
                ),
            )

        if states_equal_for_stale_check(before, observed):
            # Write likely did not occur. Mark failed safely; do not auto-retry.
            self._repository.finish_attempt(
                attempt,
                state=ApplicationAttemptState.FAILED,
                now=self._clock.now(),
                observed_state_json=observed.model_dump_json(),
                error_type="failed_before_write",
                error_message_redacted=(
                    "Remote state still matches planned before-state; write likely "
                    "did not occur"
                ),
                outcome_certainty=OutcomeCertainty.CERTAIN,
            )
            self._repository.set_item_apply_result(
                row,
                result=ApplyResultKind.TEMPORARY_FAILURE,
            )
            self._repository._session.flush()
            return RecoveryItemResult(
                item_id=UUID(row.id),
                classification="before_state_present",
                apply_result=ApplyResultKind.TEMPORARY_FAILURE,
                wrote_again=False,
                observed_state=observed,
                message=(
                    "Before-state still present; safe non-application recorded. "
                    "Create a new plan to retry."
                ),
            )

        mismatches = verification.field_mismatches
        self._repository.finish_attempt(
            attempt,
            state=ApplicationAttemptState.CONFLICT,
            now=self._clock.now(),
            observed_state_json=observed.model_dump_json(),
            error_type="recovery_conflict",
            error_message_redacted=(
                verification.message
                or "Remote state matches neither before nor intended after-state"
            ),
            outcome_certainty=OutcomeCertainty.CERTAIN,
            field_mismatches_json=json.dumps(mismatches),
        )
        self._repository.set_item_apply_result(
            row,
            result=ApplyResultKind.VERIFICATION_UNKNOWN,
        )
        self._repository._session.flush()
        return RecoveryItemResult(
            item_id=UUID(row.id),
            classification="unexpected_third_state",
            apply_result=ApplyResultKind.VERIFICATION_UNKNOWN,
            wrote_again=False,
            observed_state=observed,
            field_mismatches=mismatches,
            message="Neither before nor intended state matches; new plan required",
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


def _next_action(
    items: list[RecoveryItemResult],
    plan_state: CommandState,
) -> str:
    if any(i.classification == "unexpected_third_state" for i in items):
        return "create_new_plan"
    if any(i.classification == "before_state_present" for i in items):
        return "create_new_plan_to_retry"
    if any(i.classification == "remote_lookup_failed" for i in items):
        return "retry_recovery_later"
    if plan_state is CommandState.VERIFIED:
        return "none"
    return "inspect_history"
