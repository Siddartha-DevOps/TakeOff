"""Production configuration validation and non-secret readiness reporting."""

from __future__ import annotations

import os

PRODUCTION_ENVS = {"production", "prod", "staging"}


def is_production() -> bool:
    configured = os.environ.get("ENVIRONMENT", "development").strip().lower()
    return configured in PRODUCTION_ENVS or os.environ.get("RENDER", "").strip().lower() == "true"


def cors_origins() -> list[str]:
    return [value.strip() for value in os.environ.get("CORS_ORIGINS", "*").split(",") if value.strip()]


def validate_startup_environment() -> None:
    """Fail before serving when a production deployment is fundamentally unsafe."""
    import storage

    production = is_production()
    missing = []
    if production:
        missing.extend(name for name in ("DATABASE_URL", "JWT_SECRET_KEY") if not os.environ.get(name))
        if not os.environ.get("REDIS_URL"):
            missing.append("REDIS_URL (durable Celery broker/result backend)")
        origins = cors_origins()
        if not origins or "*" in origins:
            missing.append("CORS_ORIGINS (must be explicit in production)")
    if storage.object_storage_required() or production:
        storage_errors = storage.storage_configuration_errors()
        if storage_errors:
            missing.append("object storage (" + ", ".join(storage_errors) + ")")
    if missing:
        raise RuntimeError("Unsafe production configuration; missing/invalid: " + ", ".join(missing))


def configuration_snapshot() -> dict:
    """Return booleans only—never secret values or credential-bearing URLs."""
    from analysis_jobs import celery_worker_ready, queue_backend, redis_ready
    import storage

    storage_errors = storage.storage_configuration_errors()
    storage_ready = storage.storage_ready() if not storage_errors else False
    # Native Render services do not automatically set ENVIRONMENT=production,
    # but Render does guarantee RENDER=true. Readiness must still fail closed
    # for ephemeral upload storage even before the dashboard is normalized.
    storage_required = storage.object_storage_required() or is_production()
    broker_ready = queue_backend() == "celery" and redis_ready()
    worker_ready = broker_ready and celery_worker_ready()
    components = {
        "object_storage": {
            "ready": storage_ready,
            "required": storage_required,
            "configuration_errors": storage_errors,
        },
        "job_queue": {
            "ready": worker_ready,
            "backend": queue_backend(),
            "broker_ready": broker_ready,
            "worker_ready": worker_ready,
            "durable_across_restart": queue_backend() == "celery",
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
