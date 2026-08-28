import pytest

import production_readiness as readiness


def test_development_allows_local_defaults(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    readiness.validate_startup_environment()


def test_production_requires_database_jwt_and_explicit_cors(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="DATABASE_URL.*JWT_SECRET_KEY.*CORS_ORIGINS"):
        readiness.validate_startup_environment()


def test_production_accepts_hard_requirements(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    monkeypatch.setenv("JWT_SECRET_KEY", "configured")
    monkeypatch.setenv("CORS_ORIGINS", "https://take-off-omega.vercel.app")
    readiness.validate_startup_environment()


def test_cors_origins_are_trimmed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://one.example, https://two.example ")
    assert readiness.cors_origins() == ["https://one.example", "https://two.example"]
