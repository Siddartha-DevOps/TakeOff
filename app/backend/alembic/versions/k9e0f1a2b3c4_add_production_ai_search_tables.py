"""add production ai search OCR and review tables

Revision ID: k9e0f1a2b3c4
Revises: j8d9e0f1a2b3
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "k9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "j8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drawing_embeddings", sa.Column("encoder", sa.String(length=50), nullable=False, server_default="legacy"))
    op.create_index("ix_drawing_embeddings_project_encoder", "drawing_embeddings", ["project_id", "encoder"])
    op.add_column("drawings", sa.Column("processing_job_id", sa.String(length=64), nullable=True))
    op.add_column("drawings", sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("drawings", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("drawings", sa.Column("processing_error", sa.Text(), nullable=True))
    op.create_table(
        "drawing_text_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("drawing_id", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_kind", sa.String(length=30), nullable=False, server_default="drawing"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("bbox_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["drawing_id"], ["drawings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_drawing_text_chunks_id", "drawing_text_chunks", ["id"])
    op.create_index("ix_drawing_text_chunks_project_id", "drawing_text_chunks", ["project_id"])
    op.create_index("ix_drawing_text_chunks_drawing_id", "drawing_text_chunks", ["drawing_id"])
    op.create_index("ix_drawing_text_chunks_search", "drawing_text_chunks", ["project_id", "source_kind"])
    op.create_table(
        "search_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("drawing_id", sa.Integer(), nullable=False),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("query_kind", sa.String(length=20), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("detection_id", sa.String(length=64), nullable=True),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["drawing_id"], ["drawings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_reviews_id", "search_reviews", ["id"])
    op.create_index("ix_search_reviews_project_id", "search_reviews", ["project_id"])
    op.create_index("ix_search_reviews_drawing_id", "search_reviews", ["drawing_id"])


def downgrade() -> None:
    op.drop_table("search_reviews")
    op.drop_table("drawing_text_chunks")
    op.drop_column("drawings", "processing_error")
    op.drop_column("drawings", "processing_started_at")
    op.drop_column("drawings", "processing_attempts")
    op.drop_column("drawings", "processing_job_id")
    op.drop_index("ix_drawing_embeddings_project_encoder", table_name="drawing_embeddings")
    op.drop_column("drawing_embeddings", "encoder")
