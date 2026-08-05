"""Unit tests for resolver error taxonomy mapping helpers."""

from __future__ import annotations

from backend.app.resolver.errors import (
    ResolverAliasStoreError,
    ResolverAuthenticationError,
    ResolverEnrichmentError,
    ResolverError,
    ResolverTemporaryError,
    ResolverValidationError,
)


def test_error_codes_are_stable() -> None:
    assert ResolverError("x").error_code == "resolver_error"
    assert ResolverAuthenticationError("x").error_code == (
        "resolver_authentication_error"
    )
    assert ResolverTemporaryError("x").error_code == "resolver_temporary_error"
    assert ResolverEnrichmentError("x").error_code == "resolver_enrichment_error"
    assert ResolverAliasStoreError("x").error_code == "resolver_alias_store_error"
    assert ResolverValidationError("x", field="title").error_code == (
        "resolver_validation_error"
    )


def test_validation_error_retains_field() -> None:
    err = ResolverValidationError("bad", field="release_year")
    assert err.field == "release_year"
    assert err.message == "bad"
