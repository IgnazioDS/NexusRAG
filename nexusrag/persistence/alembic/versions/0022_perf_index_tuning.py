"""add performance indexes for document lifecycle queries

Revision ID: 0022_perf_index_tuning
Revises: 0021_sla_policy_autoscale
Create Date: 2026-02-17
"""

from __future__ import annotations

from alembic import op


revision = "0022_perf_index_tuning"
down_revision = "0021_sla_policy_autoscale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Speed up ops ingestion filters by status + queue timestamp.
    op.create_index(
        "ix_documents_status_queued_at",
        "documents",
        ["status", "queued_at"],
    )
    # Speed up processing-state windows for worker lag dashboards.
    op.create_index(
        "ix_documents_status_processing_started_at",
        "documents",
        ["status", "processing_started_at"],
    )
    # Speed up completion-state windows for success/failure percentile queries.
    op.create_index(
        "ix_documents_status_completed_at",
        "documents",
        ["status", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_status_completed_at", table_name="documents")
    op.drop_index("ix_documents_status_processing_started_at", table_name="documents")
    op.drop_index("ix_documents_status_queued_at", table_name="documents")
