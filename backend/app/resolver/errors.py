"""Typed errors for title-resolution service failures.

Normal outcomes (resolved / ambiguous / not_found) are return values, not
exceptions.
"""

from __future__ import annotations


class ResolverError(Exception):
    """Base class for exceptional title-resolution failures."""

    error_code: str = "resolver_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ResolverAuthenticationError(ResolverError):
    """MAL authentication is unavailable or reconnect is required."""

    error_code = "resolver_authentication_error"


class ResolverTemporaryError(ResolverError):
    """MAL is temporarily unavailable (network, 5xx, rate limit)."""

    error_code = "resolver_temporary_error"


class ResolverEnrichmentError(ResolverError):
    """Candidate enrichment failed entirely; no usable candidates remain."""

    error_code = "resolver_enrichment_error"


class ResolverAliasStoreError(ResolverError):
    """Alias repository read or write failed."""

    error_code = "resolver_alias_store_error"


class ResolverValidationError(ResolverError):
    """Resolver request failed local validation."""

    error_code = "resolver_validation_error"

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)
