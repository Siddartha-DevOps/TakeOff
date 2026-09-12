"""add persisted annotation state to drawings

Revision ID: i7d8e9f0a1b2
Revises: h6c7d8e9f0a1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "i7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "h6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drawings", sa.Column("annotations_data", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("drawings", "annotations_data")
