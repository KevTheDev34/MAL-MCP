"""Unit tests for PKCE helpers."""

from __future__ import annotations

import pytest

from backend.app.auth.pkce import (
    generate_code_verifier,
    generate_oauth_state,
    plain_code_challenge,
)


def test_code_verifier_length_in_range() -> None:
    verifier = generate_code_verifier()
    assert 43 <= len(verifier) <= 128


def test_plain_challenge_equals_verifier() -> None:
    verifier = generate_code_verifier(64)
    assert plain_code_challenge(verifier) == verifier


def test_verifier_rejects_short_length() -> None:
    with pytest.raises(ValueError):
        generate_code_verifier(10)


def test_oauth_state_is_nonempty() -> None:
    assert len(generate_oauth_state()) >= 16
