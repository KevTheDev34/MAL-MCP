"""Typed command-layer errors for plan/confirm/apply."""

from __future__ import annotations


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
