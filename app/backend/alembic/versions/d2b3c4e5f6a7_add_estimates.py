"""add estimates (saved priced assembly estimates)

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-07-18 09:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2b3c4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'estimates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('drawing_id', sa.Integer(), nullable=True),
        sa.Column('cost_book_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('total', sa.Float(), nullable=False),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['drawing_id'], ['drawings.id'], ),
        sa.ForeignKeyConstraint(['cost_book_id'], ['cost_books.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_estimates_id'), 'estimates', ['id'], unique=False)
    op.create_index(op.f('ix_estimates_organization_id'), 'estimates', ['organization_id'], unique=False)
    op.create_index(op.f('ix_estimates_project_id'), 'estimates', ['project_id'], unique=False)
    op.create_index(op.f('ix_estimates_drawing_id'), 'estimates', ['drawing_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_estimates_drawing_id'), table_name='estimates')
    op.drop_index(op.f('ix_estimates_project_id'), table_name='estimates')
    op.drop_index(op.f('ix_estimates_organization_id'), table_name='estimates')
    op.drop_index(op.f('ix_estimates_id'), table_name='estimates')
    op.drop_table('estimates')
