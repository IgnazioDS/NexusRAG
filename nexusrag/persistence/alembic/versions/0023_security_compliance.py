"""add security hardening and compliance snapshot tables

Revision ID: 0023_security_compliance
Revises: 0022_perf_index_tuning
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_security_compliance"
down_revision = "0022_perf_index_tuning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add optional API key expiry to enforce credential lifetimes.
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_api_keys_expires_at", "api_keys", ["expires_at"])

    # Store platform signing/encryption keys with explicit lifecycle states.
    op.create_table(
        "platform_keys",
        sa.Column("key_id", sa.String(), primary_key=True),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_platform_keys_purpose", "platform_keys", ["purpose"])
    op.create_index("ix_platform_keys_status", "platform_keys", ["status"])
    op.create_index(
        "ix_platform_keys_purpose_status_created",
        "platform_keys",
        ["purpose", "status", "created_at"],
    )

    # Persist redacted compliance snapshot payloads used by evidence bundle exports.
    op.create_table(
        "compliance_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary_json", postgresql.JSONB(), nullable=False),
        sa.Column("controls_json", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_compliance_snapshots_tenant", "compliance_snapshots", ["tenant_id"])
    op.create_index("ix_compliance_snapshots_status", "compliance_snapshots", ["status"])
    op.create_index("ix_compliance_snapshots_created", "compliance_snapshots", ["created_at"])

    # Track retention maintenance task execution metadata for governance proof points.
    op.create_table(
        "retention_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("task", sa.String(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_retention_runs_tenant", "retention_runs", ["tenant_id"])
    op.create_index("ix_retention_runs_task", "retention_runs", ["task"])
    op.create_index("ix_retention_runs_task_last_run", "retention_runs", ["task", "last_run_at"])


def downgrade() -> None:
    op.drop_index("ix_retention_runs_task_last_run", table_name="retention_runs")
    op.drop_index("ix_retention_runs_task", table_name="retention_runs")
    op.drop_index("ix_retention_runs_tenant", table_name="retention_runs")
    op.drop_table("retention_runs")

    op.drop_index("ix_compliance_snapshots_created", table_name="compliance_snapshots")
    op.drop_index("ix_compliance_snapshots_status", table_name="compliance_snapshots")
    op.drop_index("ix_compliance_snapshots_tenant", table_name="compliance_snapshots")
    op.drop_table("compliance_snapshots")

    op.drop_index("ix_platform_keys_purpose_status_created", table_name="platform_keys")
    op.drop_index("ix_platform_keys_status", table_name="platform_keys")
    op.drop_index("ix_platform_keys_purpose", table_name="platform_keys")
    op.drop_table("platform_keys")

    op.drop_index("ix_api_keys_expires_at", table_name="api_keys")
    op.drop_column("api_keys", "expires_at")
