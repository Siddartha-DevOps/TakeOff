"""Security regression: the JWT signing key must never be a hardcoded default."""

import importlib

import pytest

# auth.py imports jose/passlib; skip cleanly where the auth stack isn't installed
# (this sandbox), run in CI where it is — same pattern as test_auth_hashing.py.
pytest.importorskip("jose")
pytest.importorskip("passlib.context")

from auth import _INSECURE_DEFAULT, _load_secret_key


def test_configured_secret_is_used(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "a-strong-configured-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert _load_secret_key() == "a-strong-configured-secret"


def test_production_without_secret_fails_fast(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        _load_secret_key()


def test_production_rejects_the_insecure_placeholder(monkeypatch):
    # Even if the old default lingers in an env file, it must not sign tokens.
    monkeypatch.setenv("JWT_SECRET_KEY", _INSECURE_DEFAULT)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    with pytest.raises(RuntimeError):
        _load_secret_key()


def test_dev_generates_ephemeral_random_key(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "development")
    k1 = _load_secret_key()
    k2 = _load_secret_key()
    assert k1 and k2 and k1 != k2                 # random per call
    assert k1 != _INSECURE_DEFAULT
    assert len(k1) >= 32


def test_default_environment_is_not_production(monkeypatch):
    # No ENVIRONMENT set -> dev behavior (ephemeral key), never a hard failure.
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    key = _load_secret_key()
    assert key and key != _INSECURE_DEFAULT


def test_tokens_roundtrip_with_loaded_key(monkeypatch):
    # End-to-end: create + decode a token with the module's real key path.
    monkeypatch.setenv("JWT_SECRET_KEY", "roundtrip-secret-value")
    import auth
    importlib.reload(auth)
    try:
        token = auth.create_access_token({"sub": "42"})
        assert auth.decode_token(token)["sub"] == "42"
        assert auth.decode_token("garbage.token.here") is None
    finally:
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        importlib.reload(auth)  # restore module state for other tests
