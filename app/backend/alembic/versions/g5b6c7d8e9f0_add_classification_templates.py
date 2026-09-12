"""add classification_templates

Revision ID: g5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-07-24 15:30:00.000000

Reusable org-level classification libraries (Togal's classification library
template) — a named set of conditions an estimator applies to a project.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g5b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'classification_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_classification_templates_id'), 'classification_templates', ['id'], unique=False)
    op.create_index(op.f('ix_classification_templates_organization_id'), 'classification_templates', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_classification_templates_organization_id'), table_name='classification_templates')
    op.drop_index(op.f('ix_classification_templates_id'), table_name='classification_templates')
    op.drop_table('classification_templates')
