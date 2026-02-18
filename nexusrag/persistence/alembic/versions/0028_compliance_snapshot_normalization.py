"""normalize compliance snapshot schema for captured/results/artifact metadata

Revision ID: 0028_snapshot_schema
Revises: 0027_security_contracts
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0028_snapshot_schema"
down_revision = "0027_security_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add canonical capture timestamp and normalized results payload while preserving legacy columns.
    op.add_column("compliance_snapshots", sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("compliance_snapshots", sa.Column("results_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        "compliance_snapshots",
        sa.Column("artifact_paths_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_compliance_snapshots_captured_at", "compliance_snapshots", ["captured_at"])

    # Backfill canonical fields so pre-normalization rows remain queryable with the new response contract.
    op.execute("UPDATE compliance_snapshots SET captured_at = created_at WHERE captured_at IS NULL")
    op.execute("UPDATE compliance_snapshots SET results_json = summary_json WHERE results_json IS NULL")
    op.execute("UPDATE compliance_snapshots SET artifact_paths_json = '{}'::jsonb WHERE artifact_paths_json IS NULL")


def downgrade() -> None:
    op.drop_index("ix_compliance_snapshots_captured_at", table_name="compliance_snapshots")
    op.drop_column("compliance_snapshots", "artifact_paths_json")
    op.drop_column("compliance_snapshots", "results_json")
    op.drop_column("compliance_snapshots", "captured_at")
