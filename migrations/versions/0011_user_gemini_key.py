"""per-user gemini api key

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('encrypted_gemini_key', sa.Text(), server_default='', nullable=False))
    op.add_column('users', sa.Column('gemini_key_updated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users') as batch:
        batch.drop_column('gemini_key_updated_at')
        batch.drop_column('encrypted_gemini_key')
