"""Alembic environment for the PostGIS geometry tables.

Reads DATABASE_URL from the environment (same var the app uses) and targets the
``GeoBase`` metadata that holds the first-class geometry model.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime database URL (kept out of alembic.ini so no secrets land in
# version control).
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://takeoff_user:takeoff_dev_pass_2025@localhost/takeoff_db",
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Target metadata for autogenerate. GeoBase carries the geometry tables.
from geo_models import GeoBase  # noqa: E402

target_metadata = GeoBase.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
