"""Typed MAL API client errors (no secrets in messages)."""

from __future__ import annotations


class MalError(Exception):
    """Base class for MAL API client errors."""

    error_code: str = "mal_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class MalAuthenticationError(MalError):
    """MAL credentials missing, invalid, or reconnect required."""

    error_code = "mal_authentication_error"


class MalAuthorizationError(MalError):
    """Authenticated but not permitted to access the resource."""

    error_code = "mal_authorization_error"


class MalNotFoundError(MalError):
    """Requested MAL resource was not found."""

    error_code = "mal_not_found_error"


class MalRateLimitError(MalError):
    """MAL rate limit exceeded."""

    error_code = "mal_rate_limit_error"

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MalValidationError(MalError):
    """MAL rejected the request as invalid."""

    error_code = "mal_validation_error"


class MalTemporaryError(MalError):
    """Temporary network or MAL server failure."""

    error_code = "mal_temporary_error"


class MalUnexpectedResponseError(MalError):
    """MAL response was malformed or unexpected."""

    error_code = "mal_unexpected_response_error"
