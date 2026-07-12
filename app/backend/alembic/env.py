import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Make backend/ importable (database.py, models.py live next to alembic.ini,
# same layout server.py already assumes).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from geoalchemy2.types import Geometry  # noqa: E402

from database import Base  # noqa: E402
import models  # noqa: E402,F401 — populates Base.metadata as a side effect

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Same DATABASE_URL convention as database.py — never hardcode it in
# alembic.ini. geoalchemy2 also needs PostGIS's `spatial_ref_sys` table
# excluded from autogenerate diffs (it's owned by the extension, not us).
config.set_main_option(
    "sqlalchemy.url",
    os.environ.get(
        "DATABASE_URL",
        "postgresql://takeoff_user:takeoff_dev_pass_2025@localhost/takeoff_db",
    ),
)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    # PostGIS creates spatial_ref_sys; it's extension-owned, not app schema.
    if type_ == "table" and name == "spatial_ref_sys":
        return False
    return True


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    # geoalchemy2's reflected Geometry type doesn't round-trip srid/dimension
    # through DB introspection the same way the declared model type does,
    # which makes autogenerate report a spurious diff on every run even when
    # the schema matches (verified via geometry_columns — see PR description).
    # This is geoalchemy2's own documented workaround, not a real drift check.
    if isinstance(metadata_type, Geometry):
        return False
    return None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=compare_type,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=compare_type,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
