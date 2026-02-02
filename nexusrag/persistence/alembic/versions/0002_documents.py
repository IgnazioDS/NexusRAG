"""add documents table and chunk document linkage

Revision ID: 0002_documents
Revises: 0001_init
Create Date: 2026-02-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_documents"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create documents to track ingestion lifecycle and status.
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("corpus_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="upload"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"], unique=False)
    op.create_index("ix_documents_corpus_id", "documents", ["corpus_id"], unique=False)
    op.create_index("ix_documents_status", "documents", ["status"], unique=False)

    # Link chunks to their source document for reingestion and tracking.
    op.add_column("chunks", sa.Column("document_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_chunks_document_id",
        "chunks",
        "documents",
        ["document_id"],
        ["id"],
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_constraint("fk_chunks_document_id", "chunks", type_="foreignkey")
    op.drop_column("chunks", "document_id")

    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_corpus_id", table_name="documents")
    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_table("documents")
