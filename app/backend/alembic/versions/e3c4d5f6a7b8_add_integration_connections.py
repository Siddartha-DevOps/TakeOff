"""add integration_connections

Revision ID: e3c4d5f6a7b8
Revises: d2b3c4e5f6a7
Create Date: 2026-07-18 09:55:00.000000

External-system connections (Procore / PlanSwift / …): OAuth/API credentials +
account identity per org, so quantities/estimates can be pushed live.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3c4d5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'd2b3c4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'integration_connections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('external_account_id', sa.String(length=255), nullable=True),
        sa.Column('external_account_name', sa.String(length=255), nullable=True),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('config', sa.Text(), nullable=True),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_integration_connections_id'), 'integration_connections', ['id'], unique=False)
    op.create_index(op.f('ix_integration_connections_organization_id'), 'integration_connections', ['organization_id'], unique=False)
    op.create_index('ux_integration_org_provider', 'integration_connections', ['organization_id', 'provider'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_integration_org_provider', table_name='integration_connections')
    op.drop_index(op.f('ix_integration_connections_organization_id'), table_name='integration_connections')
    op.drop_index(op.f('ix_integration_connections_id'), table_name='integration_connections')
    op.drop_table('integration_connections')
