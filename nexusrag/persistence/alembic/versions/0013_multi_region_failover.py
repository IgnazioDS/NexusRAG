"""add multi-region failover control plane tables

Revision ID: 0013_multi_region_failover
Revises: 0012_dr_backups
Create Date: 2026-02-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_multi_region_failover"
down_revision = "0012_dr_backups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist active primary region and freeze flags for Redis loss recovery.
    op.create_table(
        "failover_cluster_state",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("active_primary_region", sa.String(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_transition_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freeze_writes", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_failover_cluster_state_active_primary",
        "failover_cluster_state",
        ["active_primary_region"],
        unique=False,
    )

    # Track per-region health and replication lag for arbitration decisions.
    op.create_table(
        "region_status",
        sa.Column("region_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("health_status", sa.String(), nullable=False),
        sa.Column("replication_lag_seconds", sa.Integer(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("writable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_region_status_health_updated",
        "region_status",
        ["health_status", "updated_at"],
        unique=False,
    )

    # Record each failover request/execution for auditability and rollback traces.
    op.create_table(
        "failover_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("from_region", sa.String(), nullable=True),
        sa.Column("to_region", sa.String(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by_actor_id", sa.String(), nullable=True),
        sa.Column("approval_token_id", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_failover_events_status_started",
        "failover_events",
        ["status", "started_at"],
        unique=False,
    )
    op.create_index("ix_failover_events_request_id", "failover_events", ["request_id"], unique=False)

    # Keep one-time promotion/rollback tokens hashed with bounded TTL.
    op.create_table(
        "failover_tokens",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("requested_by_actor_id", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("purpose", sa.String(), nullable=False),
    )
    op.create_index("ix_failover_tokens_token_hash", "failover_tokens", ["token_hash"], unique=False)
    op.create_index("ix_failover_tokens_expires_at", "failover_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_failover_tokens_expires_at", table_name="failover_tokens")
    op.drop_index("ix_failover_tokens_token_hash", table_name="failover_tokens")
    op.drop_table("failover_tokens")

    op.drop_index("ix_failover_events_request_id", table_name="failover_events")
    op.drop_index("ix_failover_events_status_started", table_name="failover_events")
    op.drop_table("failover_events")

    op.drop_index("ix_region_status_health_updated", table_name="region_status")
    op.drop_table("region_status")

    op.drop_index("ix_failover_cluster_state_active_primary", table_name="failover_cluster_state")
    op.drop_table("failover_cluster_state")
