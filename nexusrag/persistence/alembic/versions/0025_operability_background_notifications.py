"""add durable notification job tables for operability automation

Revision ID: 0025_operability_notify
Revises: 0024_operability_alerting
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_operability_notify"
down_revision = "0024_operability_alerting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist durable notification jobs so alerting and incident workflows are decoupled from request paths.
    op.create_table(
        "notification_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("incident_id", sa.String(), sa.ForeignKey("ops_incidents.id"), nullable=True),
        sa.Column("alert_event_id", sa.String(), sa.ForeignKey("alert_events.id"), nullable=True),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("dedupe_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "incident_id",
            "destination",
            "dedupe_key",
            "dedupe_window_start",
            name="uq_notification_jobs_dedupe_window",
        ),
    )
    op.create_index("ix_notification_jobs_tenant", "notification_jobs", ["tenant_id"])
    op.create_index("ix_notification_jobs_incident_id", "notification_jobs", ["incident_id"])
    op.create_index("ix_notification_jobs_alert_event_id", "notification_jobs", ["alert_event_id"])
    op.create_index("ix_notification_jobs_status", "notification_jobs", ["status"])
    op.create_index("ix_notification_jobs_next_attempt_at", "notification_jobs", ["next_attempt_at"])
    op.create_index(
        "ix_notification_jobs_tenant_status_next",
        "notification_jobs",
        ["tenant_id", "status", "next_attempt_at"],
    )
    op.create_index(
        "ix_notification_jobs_incident_created",
        "notification_jobs",
        ["incident_id", "created_at"],
    )

    # Capture every delivery attempt to support deterministic retry audits and troubleshooting.
    op.create_table(
        "notification_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("notification_jobs.id"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("job_id", "attempt_no", name="uq_notification_attempts_job_attempt"),
    )
    op.create_index("ix_notification_attempts_job_id", "notification_attempts", ["job_id"])
    op.create_index("ix_notification_attempts_outcome", "notification_attempts", ["outcome"])
    op.create_index(
        "ix_notification_attempts_job_started",
        "notification_attempts",
        ["job_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_attempts_job_started", table_name="notification_attempts")
    op.drop_index("ix_notification_attempts_outcome", table_name="notification_attempts")
    op.drop_index("ix_notification_attempts_job_id", table_name="notification_attempts")
    op.drop_table("notification_attempts")

    op.drop_index("ix_notification_jobs_incident_created", table_name="notification_jobs")
    op.drop_index("ix_notification_jobs_tenant_status_next", table_name="notification_jobs")
    op.drop_index("ix_notification_jobs_next_attempt_at", table_name="notification_jobs")
    op.drop_index("ix_notification_jobs_status", table_name="notification_jobs")
    op.drop_index("ix_notification_jobs_alert_event_id", table_name="notification_jobs")
    op.drop_index("ix_notification_jobs_incident_id", table_name="notification_jobs")
    op.drop_index("ix_notification_jobs_tenant", table_name="notification_jobs")
    op.drop_table("notification_jobs")
