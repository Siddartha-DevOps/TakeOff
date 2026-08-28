"""Process-start safeguards for the TakeOff API.

The application may be deployed either through the Docker image (whose
``start.sh`` runs Alembic) or as a native Render Python service that launches
Uvicorn directly.  Running the migration check here makes both entrypoints
safe: the API never accepts traffic against an uninitialised schema.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parent
_FALSE_VALUES = {"0", "false", "no", "off"}

_BASELINE_REVISION = "704876dee09b"
_BASELINE_TABLES = {
    "organizations", "users", "payment_transactions", "projects",
    "user_subscriptions", "conditions", "drawings", "correction_events",
    "detections", "takeoff_results", "measurements",
}

# Ordered migration fingerprints. A legacy database created by
# Base.metadata.create_all() has no alembic_version row, but its tables/columns
# reveal the newest migration it already contains.
_REVISION_MARKERS = [
    ("ec884d8cb9bd", {"conditions"}, {"conditions": {"unit_cost"}}),
    ("3f3366d51f41", {"drawing_embeddings"}, {}),
    ("50f4005e345c", set(), {"drawings": {"page_number", "total_pages", "sheet_number", "discipline", "upload_batch_id"}}),
    ("2ccc26455bd6", {"model_versions"}, {"correction_events": {"model_version"}}),
    ("6e1672d332cb", {"cost_code_mappings", "handoff_audit_events"}, {}),
    ("a8c2f331acef", {"comments"}, {}),
    ("dc9aac8a90e5", {"invites"}, {"users": {"role"}}),
    ("b6977e619493", {"master_units"}, {}),
    ("c1a2b3d4e5f6", {"assemblies", "assembly_components", "cost_books", "cost_items"}, {}),
    ("d2b3c4e5f6a7", {"estimates"}, {}),
    ("e3c4d5f6a7b8", {"integration_connections"}, {}),
    ("f4a5b6c7d8e9", {"project_shares"}, {}),
    ("g5b6c7d8e9f0", {"classification_templates"}, {}),
    ("h6c7d8e9f0a1", {"activity_logs", "sso_connections"}, {}),
    ("i7d8e9f0a1b2", set(), {"drawings": {"annotations_data"}}),
    ("j8d9e0f1a2b3", {"annotation_revisions"}, {}),
    ("k9e0f1a2b3c4", {"drawing_text_chunks", "search_reviews"}, {
        "drawing_embeddings": {"encoder"},
        "drawings": {"processing_job_id", "processing_attempts", "processing_started_at", "processing_error"},
    }),
]


def auto_migrate_enabled() -> bool:
    """Return whether this process should apply migrations before startup."""

    return os.environ.get("AUTO_MIGRATE", "true").strip().lower() not in _FALSE_VALUES


def infer_legacy_revision(tables: set[str], columns: dict[str, set[str]]) -> str | None:
    """Infer the exact Alembic revision represented by an unversioned schema.

    Returns ``None`` for a fresh/already-versioned database. A partial baseline
    or migration markers appearing after a gap are unsafe and fail closed.
    """
    if "alembic_version" in tables or not (tables & _BASELINE_TABLES):
        return None
    missing_baseline = _BASELINE_TABLES - tables
    if missing_baseline:
        raise RuntimeError(
            "Existing database has a partial pre-Alembic TakeOff schema; "
            f"missing baseline tables: {', '.join(sorted(missing_baseline))}"
        )

    highest = _BASELINE_REVISION
    gap_revision = None
    for revision, required_tables, required_columns in _REVISION_MARKERS:
        present = required_tables <= tables and all(
            needed <= columns.get(table, set())
            for table, needed in required_columns.items()
        )
        if not present:
            gap_revision = gap_revision or revision
        elif gap_revision:
            raise RuntimeError(
                "Existing database schema is inconsistent: migration marker "
                f"{revision} exists after missing marker {gap_revision}. "
                "Refusing to stamp an uncertain revision."
            )
        else:
            highest = revision
    return highest


def needs_partial_legacy_repair(tables: set[str]) -> bool:
    """Return whether an unversioned database has only part of the baseline."""

    return (
        "alembic_version" not in tables
        and bool(tables & _BASELINE_TABLES)
        and not _BASELINE_TABLES <= tables
    )


def _schema_snapshot(engine) -> tuple[set[str], dict[str, set[str]]]:
    """Read the table/column fingerprint used for legacy schema validation."""
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    relevant_tables = tables | _BASELINE_TABLES | {
        table for _, required, columns in _REVISION_MARKERS
        for table in (set(required) | set(columns))
    }
    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in relevant_tables if table in tables
    }
    return tables, columns


def _repair_partial_legacy_schema(engine) -> None:
    """Complete a schema previously interrupted during ``create_all``.

    SQLAlchemy's ``create_all`` is deliberately used only for this narrowly
    detected legacy state. It preserves existing tables and rows and creates
    missing current-model tables. The caller then fingerprints the result and
    refuses to stamp it unless it exactly represents a known revision.
    """
    from sqlalchemy import text
    from database import Base
    import models  # noqa: F401 - registers every model on Base.metadata

    logger.warning(
        "Detected partial pre-Alembic TakeOff schema; creating missing model tables"
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine, checkfirst=True)


def _stamp_legacy_schema(config, command) -> None:
    """Stamp a compatible pre-Alembic schema before normal upgrades."""
    from database import engine

    tables, columns = _schema_snapshot(engine)
    if needs_partial_legacy_repair(tables):
        _repair_partial_legacy_schema(engine)
        tables, columns = _schema_snapshot(engine)

    revision = infer_legacy_revision(tables, columns)
    if revision:
        logger.warning(
            "Detected compatible pre-Alembic schema; stamping revision %s before upgrade",
            revision,
        )
        command.stamp(config, revision)


def run_database_migrations(config_factory=None, upgrade=None) -> None:
    """Upgrade the configured database to the repository's Alembic head.

    Exceptions intentionally propagate.  Serving a partially initialised
    application is worse than failing the deployment with the real migration
    error, and it previously made Render report Live while login returned
    ``relation \"users\" does not exist``.
    """

    # Import lazily so lightweight tooling can import the application modules;
    # a real service startup still fails immediately if Alembic is missing.
    real_runtime = config_factory is None and upgrade is None
    if config_factory is None or upgrade is None:
        from alembic import command
        from alembic.config import Config

        config_factory = config_factory or Config
        upgrade = upgrade or command.upgrade

    config = config_factory(str(BACKEND_ROOT / "alembic.ini"))
    # Keep this absolute even when Uvicorn is launched from the repository
    # root or another working directory.
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    if real_runtime:
        _stamp_legacy_schema(config, command)
    logger.info("Applying database migrations to Alembic head")
    upgrade(config, "head")
    logger.info("Database migrations are current")
