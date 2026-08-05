"""Typed application-domain errors."""

from __future__ import annotations

from backend.app.domain.enums import DomainErrorCode


class DomainError(Exception):
    """Base class for application-domain errors."""

    error_code: str = "domain_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class DomainValidationError(DomainError):
    """A domain model or transition failed validation."""

    error_code = "domain_validation_error"

    def __init__(
        self,
        message: str,
        *,
        code: DomainErrorCode,
        field: str | None = None,
    ) -> None:
        self.code = code
        self.field = field
        super().__init__(message)
