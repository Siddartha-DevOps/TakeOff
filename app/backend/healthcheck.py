"""Readiness probes kept separate from the HTTP presentation layer."""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def database_ready(engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # readiness must report failure, not crash
        logger.warning("database readiness check failed: %s", exc)
        return False
