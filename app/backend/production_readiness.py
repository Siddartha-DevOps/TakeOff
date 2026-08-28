"""Production configuration validation and non-secret readiness reporting."""

from __future__ import annotations

import os

PRODUCTION_ENVS = {"production", "prod", "staging"}


def is_production() -> bool:
    return os.environ.get("ENVIRONMENT", "development").strip().lower() in PRODUCTION_ENVS


def cors_origins() -> list[str]:
    return [value.strip() for value in os.environ.get("CORS_ORIGINS", "*").split(",") if value.strip()]


def validate_startup_environment() -> None:
    """Fail before serving when a production deployment is fundamentally unsafe."""
    if not is_production():
        return
    missing = [name for name in ("DATABASE_URL", "JWT_SECRET_KEY") if not os.environ.get(name)]
    origins = cors_origins()
    if not origins or "*" in origins:
        missing.append("CORS_ORIGINS (must be explicit in production)")
    if missing:
        raise RuntimeError("Unsafe production configuration; missing/invalid: " + ", ".join(missing))


def configuration_snapshot() -> dict:
    """Return booleans only—never secret values or credential-bearing URLs."""
    from analysis_jobs import queue_backend
    import storage

    storage_ready = storage.storage_available()
    storage_required = storage.object_storage_required()
    components = {
        "object_storage": {
            "ready": storage_ready,
            "required": storage_required,
        },
        "job_queue": {
            "ready": queue_backend() != "unavailable",
            "backend": queue_backend(),
            "durable_across_restart": queue_backend() in {"celery", "database_recovery"},
        },
        "ai_search": {
            "ready": bool(os.environ.get("AI_INFERENCE_SPACE_ID") and os.environ.get("HF_TOKEN")),
        },
        "observability": {"ready": bool(os.environ.get("SENTRY_DSN"))},
        "integration_encryption": {"ready": bool(os.environ.get("INTEGRATION_ENCRYPTION_KEYS"))},
        "completion_webhook": {"ready": bool(os.environ.get("INTERNAL_WEBHOOK_SECRET"))},
    }
    required_ready = all(
        component["ready"]
        for name, component in components.items()
        if name in {"object_storage", "job_queue", "ai_search"}
        and (name != "object_storage" or storage_required)
    )
    return {"production": is_production(), "release_ready": required_ready, "components": components}
