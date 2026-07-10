"""Add symbol_counts column to takeoff_results.

Stores per-type symbol counts (doors/windows/fixtures) produced by AUTODETECT /
detect_symbols as a JSON string, alongside the existing detection/quantities
JSON. First-class per-instance symbol geometry lands in the ``detections`` table
(migration 0001); this column is the fast summary the UI/export read.

Revision ID: 0002_add_symbol_counts
Revises: 0001_postgis_geometry
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_symbol_counts"
down_revision = "0001_postgis_geometry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("takeoff_results", sa.Column("symbol_counts", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("takeoff_results", "symbol_counts")
