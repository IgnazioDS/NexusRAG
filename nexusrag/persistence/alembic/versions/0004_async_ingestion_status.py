"""add async ingestion status fields

Revision ID: 0004_async_ingestion_status
Revises: 0003_document_lifecycle
Create Date: 2026-02-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_async_ingestion_status"
down_revision = "0003_document_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Track async ingestion lifecycle timestamps and job metadata.
    op.add_column("documents", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "documents", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("documents", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("last_job_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "last_job_id")
    op.drop_column("documents", "completed_at")
    op.drop_column("documents", "processing_started_at")
    op.drop_column("documents", "queued_at")
    op.drop_column("documents", "failure_reason")
