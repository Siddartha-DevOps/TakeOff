import pytest

import production_readiness as readiness


def test_development_allows_local_defaults(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("RENDER", raising=False)
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


def test_render_runtime_is_detected_as_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("RENDER", "true")
    assert readiness.is_production() is True


def test_production_accepts_hard_requirements(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    monkeypatch.setenv("JWT_SECRET_KEY", "configured")
    monkeypatch.setenv("CORS_ORIGINS", "https://take-off-omega.vercel.app")
    monkeypatch.setenv("S3_BUCKET", "takeoff-production")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    readiness.validate_startup_environment()


def test_explicit_storage_requirement_fails_startup_outside_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("REQUIRE_OBJECT_STORAGE", "true")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    with pytest.raises(RuntimeError, match="object storage.*S3_BUCKET"):
        readiness.validate_startup_environment()


def test_s3_compatible_endpoint_requires_complete_credentials(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("REQUIRE_OBJECT_STORAGE", "true")
    monkeypatch.setenv("S3_BUCKET", "takeoff")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "access")
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(RuntimeError, match="S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY"):
        readiness.validate_startup_environment()


def test_cors_origins_are_trimmed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://one.example, https://two.example ")
    assert readiness.cors_origins() == ["https://one.example", "https://two.example"]
