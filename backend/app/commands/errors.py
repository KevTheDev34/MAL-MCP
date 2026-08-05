"""Typed command-layer errors for plan/confirm/apply/audit/undo."""

from __future__ import annotations

from typing import Any


class CommandError(Exception):
    """Base class for command workflow errors."""

    error_code: str = "command_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class PlanNotFoundError(CommandError):
    error_code = "plan_not_found"


class PlanOwnershipError(CommandError):
    error_code = "plan_ownership_error"


class PlanExpiredError(CommandError):
    error_code = "plan_expired"


class PlanRevisionMismatchError(CommandError):
    error_code = "plan_revision_mismatch"


class PlanHashMismatchError(CommandError):
    error_code = "plan_hash_mismatch"


class PlanNotConfirmableError(CommandError):
    error_code = "plan_not_confirmable"


class PlanNotApplyableError(CommandError):
    error_code = "plan_not_applyable"


class PlanAlreadyAppliedError(CommandError):
    error_code = "plan_already_applied"


class PlanConflictError(CommandError):
    error_code = "plan_conflict"


class PlanConcurrencyError(CommandError):
    error_code = "plan_concurrency_error"


class PlanCanceledError(CommandError):
    error_code = "plan_canceled"


class PlanValidationError(CommandError):
    """Request-level validation failure before planning begins."""

    error_code = "plan_validation_error"

    def __init__(
        self,
        message: str,
        *,
        code: str,
        field: str | None = None,
    ) -> None:
        self.code = code
        self.field = field
        super().__init__(message)


class PlanResolveFailedError(CommandError):
    """Title resolution failed for the whole plan (auth/temporary)."""

    error_code = "plan_resolve_failed"

    def __init__(self, message: str, *, code: str) -> None:
        self.code = code
        super().__init__(message)


class AuditError(CommandError):
    """Base class for audit / history / idempotency errors."""

    error_code = "audit_error"


class HistoryNotFoundError(AuditError):
    error_code = "history_not_found"


class IdempotencyConflictError(AuditError):
    error_code = "idempotency_conflict"


class AttemptAlreadyInProgressError(AuditError):
    error_code = "attempt_already_in_progress"


class AttemptOutcomeUnknownError(AuditError):
    error_code = "attempt_outcome_unknown"


class RecoveryNotRequiredError(AuditError):
    error_code = "recovery_not_required"


class UndoError(CommandError):
    """Base class for undo / reverse-plan errors."""

    error_code = "undo_error"


class UndoNotEligibleError(UndoError):
    error_code = "undo_not_eligible"


class UndoAlreadyCompletedError(UndoError):
    error_code = "undo_already_completed"


class UndoConflictError(UndoError):
    error_code = "undo_conflict"

    def __init__(
        self,
        message: str,
        *,
        conflict: dict[str, Any] | None = None,
    ) -> None:
        self.conflict = conflict or {}
        super().__init__(message)


class UndoSourceNotVerifiedError(UndoError):
    error_code = "undo_source_not_verified"


class UndoTargetMissingError(UndoError):
    error_code = "undo_target_missing"


class UndoInProgressError(UndoError):
    error_code = "undo_in_progress"
