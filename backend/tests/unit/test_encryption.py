"""Unit tests for EncryptionService."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from backend.app.services.encryption import EncryptionError, EncryptionService


def test_encrypt_decrypt_round_trip() -> None:
    key = Fernet.generate_key().decode("utf-8")
    service = EncryptionService(key)
    ciphertext = service.encrypt("secret-value")
    assert ciphertext != "secret-value"
    assert service.decrypt(ciphertext) == "secret-value"


def test_empty_key_rejects_encrypt() -> None:
    service = EncryptionService("")
    with pytest.raises(EncryptionError, match="not configured"):
        service.encrypt("x")


def test_invalid_key_raises() -> None:
    with pytest.raises(EncryptionError, match="invalid"):
        EncryptionService("not-a-fernet-key")


def test_wrong_key_decrypt_fails() -> None:
    key_a = Fernet.generate_key().decode("utf-8")
    key_b = Fernet.generate_key().decode("utf-8")
    ciphertext = EncryptionService(key_a).encrypt("secret-value")
    with pytest.raises(EncryptionError, match="Failed to decrypt"):
        EncryptionService(key_b).decrypt(ciphertext)
