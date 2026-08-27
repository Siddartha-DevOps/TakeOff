"""add annotation version history

Revision ID: j8d9e0f1a2b3
Revises: i7d8e9f0a1b2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "j8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "i7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "annotation_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("drawing_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("annotations_data", sa.Text(), nullable=False),
        sa.Column("annotation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["drawing_id"], ["drawings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_annotation_revisions_id"), "annotation_revisions", ["id"], unique=False)
    op.create_index(op.f("ix_annotation_revisions_drawing_id"), "annotation_revisions", ["drawing_id"], unique=False)
    op.create_index(op.f("ix_annotation_revisions_created_at"), "annotation_revisions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_annotation_revisions_created_at"), table_name="annotation_revisions")
    op.drop_index(op.f("ix_annotation_revisions_drawing_id"), table_name="annotation_revisions")
    op.drop_index(op.f("ix_annotation_revisions_id"), table_name="annotation_revisions")
    op.drop_table("annotation_revisions")
