"""add project_shares (external collaboration)

Revision ID: f4a5b6c7d8e9
Revises: e3c4d5f6a7b8
Create Date: 2026-07-23 20:10:00.000000

Tokenized, account-free share links so people outside the org can view/comment
on a project (Togal's external collaboration).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3c4d5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'project_shares',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_project_shares_id'), 'project_shares', ['id'], unique=False)
    op.create_index(op.f('ix_project_shares_project_id'), 'project_shares', ['project_id'], unique=False)
    op.create_index(op.f('ix_project_shares_organization_id'), 'project_shares', ['organization_id'], unique=False)
    op.create_index(op.f('ix_project_shares_token'), 'project_shares', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_project_shares_token'), table_name='project_shares')
    op.drop_index(op.f('ix_project_shares_organization_id'), table_name='project_shares')
    op.drop_index(op.f('ix_project_shares_project_id'), table_name='project_shares')
    op.drop_index(op.f('ix_project_shares_id'), table_name='project_shares')
    op.drop_table('project_shares')
