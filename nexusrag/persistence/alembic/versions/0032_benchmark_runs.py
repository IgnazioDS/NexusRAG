"""add benchmark_runs table

Revision ID: 0032_benchmark_runs
Revises: 0031_query_log
Create Date: 2026-05-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032_benchmark_runs"
down_revision = "0031_query_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One row per public benchmark run. /api/benchmark-latest reads the two
    # most recent. embedding_provider records semantic ("vertex") vs lexical
    # ("fake") so retrieval quality is never read out of context. Mirrors the
    # BenchmarkRun model in nexusrag/domain/models.py.
    op.create_table(
        "benchmark_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fixture_version", sa.String(length=64), nullable=False),
        sa.Column("embedding_provider", sa.String(length=32), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("artifact_url", sa.Text(), nullable=True),
    )
    # Two indexes match the model (index=True on the column + the explicit
    # descending index used by the latest-runs query).
    op.create_index(
        "ix_benchmark_runs_generated_at",
        "benchmark_runs",
        ["generated_at"],
        unique=False,
    )
    op.create_index(
        "ix_benchmark_runs_generated_at_desc",
        "benchmark_runs",
        [sa.text("generated_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_benchmark_runs_generated_at_desc", table_name="benchmark_runs")
    op.drop_index("ix_benchmark_runs_generated_at", table_name="benchmark_runs")
    op.drop_table("benchmark_runs")
