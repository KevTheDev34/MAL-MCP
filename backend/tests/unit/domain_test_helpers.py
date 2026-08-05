"""Shared helpers for domain unit tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.domain.errors import DomainValidationError


def domain_error_from(
    exc_info: pytest.ExceptionInfo[BaseException],
) -> DomainValidationError:
    """Unwrap DomainValidationError from direct raise or Pydantic ctx."""
    err = exc_info.value
    if isinstance(err, DomainValidationError):
        return err
    if isinstance(err, ValidationError):
        for detail in err.errors():
            ctx = detail.get("ctx") or {}
            error = ctx.get("error")
            if isinstance(error, DomainValidationError):
                return error
    raise AssertionError(f"Expected DomainValidationError, got {exc_info.value!r}")
