"""PKCE helpers for MAL OAuth (plain method only)."""

from __future__ import annotations

import secrets
import string

# MAL requires code_verifier length between 43 and 128 characters.
_PKCE_ALPHABET = string.ascii_letters + string.digits + "-._~"
_DEFAULT_VERIFIER_LENGTH = 64


def generate_code_verifier(length: int = _DEFAULT_VERIFIER_LENGTH) -> str:
    """Generate a PKCE code_verifier suitable for MAL ``plain`` challenge."""
    if length < 43 or length > 128:
        raise ValueError("code_verifier length must be between 43 and 128")
    return "".join(secrets.choice(_PKCE_ALPHABET) for _ in range(length))


def plain_code_challenge(code_verifier: str) -> str:
    """Return the ``plain`` code_challenge (identical to the verifier)."""
    if len(code_verifier) < 43 or len(code_verifier) > 128:
        raise ValueError("code_verifier length must be between 43 and 128")
    return code_verifier


def generate_oauth_state() -> str:
    """Generate a high-entropy OAuth state parameter."""
    return secrets.token_urlsafe(32)
