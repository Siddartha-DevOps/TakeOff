"""add activity_log + sso_connections

Revision ID: h6c7d8e9f0a1
Revises: g5b6c7d8e9f0
Create Date: 2026-07-24 15:50:00.000000

Enterprise: a general org activity/audit log and per-org SAML SSO config.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h6c7d8e9f0a1'
down_revision: Union[str, Sequence[str], None] = 'g5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'activity_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=True),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_activity_log_id'), 'activity_log', ['id'], unique=False)
    op.create_index(op.f('ix_activity_log_organization_id'), 'activity_log', ['organization_id'], unique=False)
    op.create_index(op.f('ix_activity_log_created_at'), 'activity_log', ['created_at'], unique=False)

    op.create_table(
        'sso_connections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('idp_entity_id', sa.String(length=255), nullable=True),
        sa.Column('idp_sso_url', sa.String(length=500), nullable=True),
        sa.Column('idp_x509_cert', sa.Text(), nullable=True),
        sa.Column('sp_entity_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sso_connections_id'), 'sso_connections', ['id'], unique=False)
    op.create_index(op.f('ix_sso_connections_organization_id'), 'sso_connections', ['organization_id'], unique=False)
    op.create_index('ux_sso_connections_org', 'sso_connections', ['organization_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_sso_connections_org', table_name='sso_connections')
    op.drop_index(op.f('ix_sso_connections_organization_id'), table_name='sso_connections')
    op.drop_index(op.f('ix_sso_connections_id'), table_name='sso_connections')
    op.drop_table('sso_connections')

    op.drop_index(op.f('ix_activity_log_created_at'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_organization_id'), table_name='activity_log')
    op.drop_index(op.f('ix_activity_log_id'), table_name='activity_log')
    op.drop_table('activity_log')
