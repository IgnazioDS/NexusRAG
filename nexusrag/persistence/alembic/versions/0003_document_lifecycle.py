"""add document lifecycle fields

Revision ID: 0003_document_lifecycle
Revises: 0002_documents
Create Date: 2026-02-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_document_lifecycle"
down_revision = "0002_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Track ingestion source and reindexing metadata for lifecycle operations.
    op.add_column(
        "documents",
        sa.Column(
            "ingest_source",
            sa.String(),
            nullable=False,
            server_default="upload_file",
        ),
    )
    op.add_column("documents", sa.Column("storage_path", sa.String(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "documents",
        sa.Column("last_reindexed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "last_reindexed_at")
    op.drop_column("documents", "metadata_json")
    op.drop_column("documents", "storage_path")
    op.drop_column("documents", "ingest_source")
