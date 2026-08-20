"""add assemblies, assembly_components, cost_books, cost_items

Revision ID: c1a2b3d4e5f6
Revises: b6977e619493
Create Date: 2026-07-18 08:50:00.000000

Persists the trade-assemblies estimating layer: org-editable assemblies + their
component line items, and named cost books (unit-price lists). The code library
(estimating/assemblies.ASSEMBLY_LIBRARY) remains the default seed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b6977e619493'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'assemblies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('trade', sa.String(length=100), nullable=False),
        sa.Column('driver_unit', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assemblies_id'), 'assemblies', ['id'], unique=False)
    op.create_index(op.f('ix_assemblies_organization_id'), 'assemblies', ['organization_id'], unique=False)
    op.create_index('ux_assemblies_org_key', 'assemblies', ['organization_id', 'key'], unique=True)

    op.create_table(
        'assembly_components',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('assembly_id', sa.Integer(), nullable=False),
        sa.Column('item', sa.String(length=255), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=False),
        sa.Column('factor', sa.Float(), nullable=False),
        sa.Column('waste_pct', sa.Float(), nullable=False),
        sa.Column('trade', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['assembly_id'], ['assemblies.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_assembly_components_id'), 'assembly_components', ['id'], unique=False)
    op.create_index(op.f('ix_assembly_components_assembly_id'), 'assembly_components', ['assembly_id'], unique=False)

    op.create_table(
        'cost_books',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cost_books_id'), 'cost_books', ['id'], unique=False)
    op.create_index(op.f('ix_cost_books_organization_id'), 'cost_books', ['organization_id'], unique=False)

    op.create_table(
        'cost_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cost_book_id', sa.Integer(), nullable=False),
        sa.Column('item', sa.String(length=255), nullable=False),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('unit_cost', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['cost_book_id'], ['cost_books.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cost_items_id'), 'cost_items', ['id'], unique=False)
    op.create_index(op.f('ix_cost_items_cost_book_id'), 'cost_items', ['cost_book_id'], unique=False)
    op.create_index('ux_cost_items_book_item', 'cost_items', ['cost_book_id', 'item'], unique=True)


def downgrade() -> None:
    op.drop_index('ux_cost_items_book_item', table_name='cost_items')
    op.drop_index(op.f('ix_cost_items_cost_book_id'), table_name='cost_items')
    op.drop_index(op.f('ix_cost_items_id'), table_name='cost_items')
    op.drop_table('cost_items')

    op.drop_index(op.f('ix_cost_books_organization_id'), table_name='cost_books')
    op.drop_index(op.f('ix_cost_books_id'), table_name='cost_books')
    op.drop_table('cost_books')

    op.drop_index(op.f('ix_assembly_components_assembly_id'), table_name='assembly_components')
    op.drop_index(op.f('ix_assembly_components_id'), table_name='assembly_components')
    op.drop_table('assembly_components')

    op.drop_index('ux_assemblies_org_key', table_name='assemblies')
    op.drop_index(op.f('ix_assemblies_organization_id'), table_name='assemblies')
    op.drop_index(op.f('ix_assemblies_id'), table_name='assemblies')
    op.drop_table('assemblies')
