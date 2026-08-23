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


def auto_migrate_enabled() -> bool:
    """Return whether this process should apply migrations before startup."""

    return os.environ.get("AUTO_MIGRATE", "true").strip().lower() not in _FALSE_VALUES


def run_database_migrations(config_factory=None, upgrade=None) -> None:
    """Upgrade the configured database to the repository's Alembic head.

    Exceptions intentionally propagate.  Serving a partially initialised
    application is worse than failing the deployment with the real migration
    error, and it previously made Render report Live while login returned
    ``relation \"users\" does not exist``.
    """

    # Import lazily so lightweight tooling can import the application modules;
    # a real service startup still fails immediately if Alembic is missing.
    if config_factory is None or upgrade is None:
        from alembic import command
        from alembic.config import Config

        config_factory = config_factory or Config
        upgrade = upgrade or command.upgrade

    config = config_factory(str(BACKEND_ROOT / "alembic.ini"))
    # Keep this absolute even when Uvicorn is launched from the repository
    # root or another working directory.
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    logger.info("Applying database migrations to Alembic head")
    upgrade(config, "head")
    logger.info("Database migrations are current")
