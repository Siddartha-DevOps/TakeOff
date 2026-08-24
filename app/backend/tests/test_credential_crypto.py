from cryptography.fernet import Fernet
import pytest

from credential_crypto import (
    PREFIX,
    CredentialEncryptionError,
    encrypt_credential,
    is_encrypted,
    normalize_credential,
)


def _env(*keys):
    return {"INTEGRATION_ENCRYPTION_KEYS": ",".join(key.decode() for key in keys)}


def test_encrypts_and_authenticates_credentials():
    key = Fernet.generate_key()
    encrypted = encrypt_credential("provider-secret", _env(key))
    assert encrypted.startswith(PREFIX)
    assert "provider-secret" not in encrypted
    plaintext, normalized, changed = normalize_credential(encrypted, _env(key))
    assert (plaintext, normalized, changed) == ("provider-secret", encrypted, False)


def test_legacy_plaintext_is_upgraded_on_use():
    key = Fernet.generate_key()
    plaintext, encrypted, changed = normalize_credential("legacy-secret", _env(key))
    assert plaintext == "legacy-secret"
    assert is_encrypted(encrypted)
    assert changed is True


def test_old_key_ciphertext_is_rotated_to_primary_key():
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()
    old_ciphertext = encrypt_credential("rotate-me", _env(old_key))
    plaintext, rotated, changed = normalize_credential(old_ciphertext, _env(new_key, old_key))
    assert plaintext == "rotate-me"
    assert changed is True
    # The retired key can no longer decrypt the normalized value.
    with pytest.raises(CredentialEncryptionError):
        normalize_credential(rotated, _env(old_key))
    assert normalize_credential(rotated, _env(new_key))[0] == "rotate-me"


def test_tampered_ciphertext_fails_closed():
    key = Fernet.generate_key()
    encrypted = encrypt_credential("secret", _env(key))
    tampered = encrypted[:-2] + "aa"
    with pytest.raises(CredentialEncryptionError, match="authenticated"):
        normalize_credential(tampered, _env(key))


def test_missing_or_invalid_key_configuration_fails_closed():
    with pytest.raises(CredentialEncryptionError, match="not configured"):
        encrypt_credential("secret", {})
    with pytest.raises(CredentialEncryptionError, match="invalid Fernet"):
        encrypt_credential("secret", {"INTEGRATION_ENCRYPTION_KEYS": "not-a-key"})


def test_integration_route_never_assigns_plain_api_key():
    source = open("routes/integrations_routes.py", encoding="utf-8").read()
    assert "conn.access_token = body.api_key" not in source
    assert "conn.access_token = encrypt_credential(body.api_key)" in source

