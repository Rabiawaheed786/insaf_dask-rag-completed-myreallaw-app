"""admin managed ai provider settings

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ai_provider_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider_name', sqlmodel.sql.sqltypes.AutoString(), server_default='gemini', nullable=False),
    sa.Column('model_name', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False),
    sa.Column('encrypted_api_key', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('ai_provider_settings')
