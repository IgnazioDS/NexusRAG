"""add notification routing policies and dead-letter queue tables

Revision ID: 0029_notify_routing_dlq
Revises: 0028_snapshot_schema
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0029_notify_routing_dlq"
down_revision = "0028_snapshot_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist tenant-scoped route policies so notification destination selection is rule-driven and deterministic.
    op.create_table(
        "notification_routes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("match_json", postgresql.JSONB(), nullable=True),
        sa.Column("destinations_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notification_routes_tenant_id", "notification_routes", ["tenant_id"])
    op.create_index(
        "ix_notification_routes_tenant_enabled_priority",
        "notification_routes",
        ["tenant_id", "enabled", "priority"],
    )

    # Store terminal failures in a DLQ table so operators can inspect and replay safely.
    op.create_table(
        "notification_dead_letters",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("notification_jobs.id"), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", name="uq_notification_dead_letters_job"),
    )
    op.create_index("ix_notification_dead_letters_tenant", "notification_dead_letters", ["tenant_id"])
    op.create_index("ix_notification_dead_letters_job_id", "notification_dead_letters", ["job_id"])
    op.create_index(
        "ix_notification_dead_letters_tenant_created",
        "notification_dead_letters",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_dead_letters_tenant_created", table_name="notification_dead_letters")
    op.drop_index("ix_notification_dead_letters_job_id", table_name="notification_dead_letters")
    op.drop_index("ix_notification_dead_letters_tenant", table_name="notification_dead_letters")
    op.drop_table("notification_dead_letters")

    op.drop_index("ix_notification_routes_tenant_enabled_priority", table_name="notification_routes")
    op.drop_index("ix_notification_routes_tenant_id", table_name="notification_routes")
    op.drop_table("notification_routes")
