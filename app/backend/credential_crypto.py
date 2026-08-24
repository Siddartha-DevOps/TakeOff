"""Authenticated encryption for third-party integration credentials.

``INTEGRATION_ENCRYPTION_KEYS`` is a comma-separated Fernet key ring. The first
key encrypts new values; remaining keys decrypt older values during rotation.
Values carry a version prefix so legacy plaintext rows can be upgraded safely.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

PREFIX = "enc:v1:"


class CredentialEncryptionError(RuntimeError):
    """Credential encryption is unavailable or stored data failed authentication."""


def _fernet_ring(env: Optional[Mapping[str, str]] = None) -> list[Fernet]:
    source = os.environ if env is None else env
    raw = source.get("INTEGRATION_ENCRYPTION_KEYS", "")
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    if not keys:
        raise CredentialEncryptionError(
            "INTEGRATION_ENCRYPTION_KEYS is not configured. Generate a key with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`."
        )
    try:
        return [Fernet(key.encode("ascii")) for key in keys]
    except (ValueError, UnicodeEncodeError) as exc:
        raise CredentialEncryptionError(
            "INTEGRATION_ENCRYPTION_KEYS contains an invalid Fernet key"
        ) from exc


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value and value.startswith(PREFIX))


def encrypt_credential(value: Optional[str], env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    if value is None:
        return None
    primary = _fernet_ring(env)[0]
    token = primary.encrypt(value.encode("utf-8")).decode("ascii")
    return f"{PREFIX}{token}"


def normalize_credential(
    value: Optional[str], env: Optional[Mapping[str, str]] = None,
) -> tuple[Optional[str], Optional[str], bool]:
    """Return ``(plaintext, encrypted_value, changed)``.

    Legacy plaintext is encrypted with the primary key. Ciphertext made with a
    retired key is decrypted by the ring and re-encrypted with the primary key.
    Authenticated decryption rejects tampered or incorrectly keyed values.
    """
    if value is None:
        return None, None, False
    ring = _fernet_ring(env)
    if not is_encrypted(value):
        return value, encrypt_credential(value, env), True

    token = value[len(PREFIX):].encode("ascii")
    try:
        plaintext = ring[0].decrypt(token).decode("utf-8")
        return plaintext, value, False
    except InvalidToken:
        try:
            plaintext = MultiFernet(ring).decrypt(token).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise CredentialEncryptionError(
                "Stored integration credential could not be authenticated"
            ) from exc
        return plaintext, encrypt_credential(plaintext, env), True

