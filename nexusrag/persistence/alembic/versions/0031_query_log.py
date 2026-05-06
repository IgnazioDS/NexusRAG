"""add query_log table for public /api/stats aggregation

Revision ID: 0031_query_log
Revises: 0030_notify_delivery_guarantees
Create Date: 2026-04-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031_query_log"
down_revision = "0030_notify_delivery_guarantees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persistent record of each end-to-end RAG query for the public /api/stats
    # aggregator. Counters survive cold starts because they are derived from
    # this table on read rather than from in-memory state.
    op.create_table(
        "query_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        # Pre-computed end-to-end latency so the percentile query stays a single
        # PERCENTILE_CONT call without extract() arithmetic on every row.
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("retrieved_chunks", sa.Integer(), nullable=False, server_default="0"),
        # Constrained vocabulary keeps the aggregator's WHERE clauses cheap.
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "status IN ('ok', 'error', 'cancelled')",
            name="ck_query_log_status",
        ),
    )
    # Descending index on completed_at supports the rolling-window queries
    # (queries_24h, queries_7d, p50/p95 over last 24h) without a sequential scan.
    op.create_index(
        "ix_query_log_completed_at_desc",
        "query_log",
        [sa.text("completed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_query_log_completed_at_desc", table_name="query_log")
    op.drop_table("query_log")
