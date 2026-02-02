"""init

Revision ID: 0001_init
Revises: 
Create Date: 2026-02-01 18:10:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

from nexusrag.core.config import EMBED_DIM

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector is enabled for every environment, not just manual setup.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), primary_key=True),
        # Avoid index=True here because we create explicit indexes below.
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Avoid index=True here because we create explicit indexes below.
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id")),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])

    op.create_table(
        "checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Avoid index=True here because we create explicit indexes below.
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id")),
        sa.Column("state_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_checkpoints_session_id", "checkpoints", ["session_id"])

    op.create_table(
        "corpora",
        sa.Column("id", sa.String(), primary_key=True),
        # Avoid index=True here because we create explicit indexes below.
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("provider_config_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_corpora_tenant_id", "corpora", ["tenant_id"])

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Avoid index=True here because we create explicit indexes below.
        sa.Column("corpus_id", sa.String(), nullable=False),
        sa.Column("document_uri", sa.String(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        # Keep schema aligned with the embedding dimension used at runtime.
        sa.Column("embedding", Vector(EMBED_DIM)),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_chunks_corpus_id", "chunks", ["corpus_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_corpus_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_corpora_tenant_id", table_name="corpora")
    op.drop_table("corpora")
    op.drop_index("ix_checkpoints_session_id", table_name="checkpoints")
    op.drop_table("checkpoints")
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_sessions_tenant_id", table_name="sessions")
    op.drop_table("sessions")
