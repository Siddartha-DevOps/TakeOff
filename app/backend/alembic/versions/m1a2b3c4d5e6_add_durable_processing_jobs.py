"""add durable processing jobs

Revision ID: m1a2b3c4d5e6
Revises: l0f1a2b3c4d5
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "m1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "l0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("drawing_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["drawing_id"], ["drawings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_processing_jobs_org_idempotency"),
    )
    op.create_index("ix_processing_jobs_organization_id", "processing_jobs", ["organization_id"])
    op.create_index("ix_processing_jobs_project_id", "processing_jobs", ["project_id"])
    op.create_index("ix_processing_jobs_drawing_id", "processing_jobs", ["drawing_id"])
    op.create_index("ix_processing_jobs_recovery", "processing_jobs", ["status", "updated_at"])
    op.create_index("ix_processing_jobs_drawing_type", "processing_jobs", ["drawing_id", "job_type"])
    op.add_column("takeoff_results", sa.Column("processing_job_id", sa.String(length=64), nullable=True))
    op.create_index("ix_takeoff_results_processing_job_id", "takeoff_results", ["processing_job_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_takeoff_results_processing_job_id", table_name="takeoff_results")
    op.drop_column("takeoff_results", "processing_job_id")
    op.drop_table("processing_jobs")
