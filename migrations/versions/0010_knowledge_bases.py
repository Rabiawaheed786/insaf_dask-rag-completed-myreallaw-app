"""user knowledge bases and chunks

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('knowledge_bases',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('system_prompt', sqlmodel.sql.sqltypes.AutoString(), server_default='', nullable=False),
    sa.Column('embed_token', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_bases_user_id'), 'knowledge_bases', ['user_id'], unique=False)
    op.create_index(op.f('ix_knowledge_bases_embed_token'), 'knowledge_bases', ['embed_token'], unique=True)

    op.create_table('knowledge_chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kb_id', sa.Integer(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('text', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('embedding', sa.LargeBinary(), nullable=False),
    sa.Column('dim', sa.Integer(), nullable=False),
    sa.Column('embedder', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_knowledge_chunks_user_id'), 'knowledge_chunks', ['user_id'], unique=False)
    op.create_index(op.f('ix_knowledge_chunks_kb_id'), 'knowledge_chunks', ['kb_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_knowledge_chunks_kb_id'), table_name='knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_chunks_user_id'), table_name='knowledge_chunks')
    op.drop_table('knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_bases_embed_token'), table_name='knowledge_bases')
    op.drop_index(op.f('ix_knowledge_bases_user_id'), table_name='knowledge_bases')
    op.drop_table('knowledge_bases')
