"""Fernet-based encryption for secrets at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""


class EncryptionService:
    """Encrypt and decrypt UTF-8 strings with a Fernet key."""

    def __init__(self, key: str) -> None:
        if not key:
            self._fernet: Fernet | None = None
            return
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise EncryptionError("TOKEN_ENCRYPTION_KEY is invalid") from exc

    def encrypt(self, plaintext: str) -> str:
        """Return Fernet ciphertext as a UTF-8 string."""
        if self._fernet is None:
            raise EncryptionError("TOKEN_ENCRYPTION_KEY is not configured")
        try:
            return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            raise EncryptionError("Failed to encrypt value") from exc

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a Fernet ciphertext string to UTF-8 plaintext."""
        if self._fernet is None:
            raise EncryptionError("TOKEN_ENCRYPTION_KEY is not configured")
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise EncryptionError("Failed to decrypt value") from exc
        except Exception as exc:
            raise EncryptionError("Failed to decrypt value") from exc
