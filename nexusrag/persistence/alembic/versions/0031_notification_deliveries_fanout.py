"""add per-destination notification deliveries for fanout and effectively-once semantics

Revision ID: 0031_notification_deliveries_fanout
Revises: 0030_notify_delivery_guarantees
Create Date: 2026-02-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0031_notification_deliveries_fanout"
down_revision = "0030_notify_delivery_guarantees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist destination-scoped delivery state so retries and DLQ transitions are isolated per endpoint.
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("destination_id", sa.String(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("delivery_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["job_id"], ["notification_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "destination_id", name="uq_notification_deliveries_job_destination"),
    )
    op.create_index(
        "ix_notification_deliveries_tenant_status_next",
        "notification_deliveries",
        ["tenant_id", "status", "next_attempt_at"],
    )
    op.create_index(
        "ix_notification_deliveries_job_created",
        "notification_deliveries",
        ["job_id", "created_at"],
    )
    op.create_index("ix_notification_deliveries_destination_id", "notification_deliveries", ["destination_id"])
    op.create_index("ix_notification_deliveries_delivery_key", "notification_deliveries", ["delivery_key"])

    # Persist delivery ownership on attempts so per-destination observability and retries can query immutable history.
    op.add_column("notification_attempts", sa.Column("delivery_id", sa.String(), nullable=True))
    op.create_index(
        "ix_notification_attempts_delivery_started",
        "notification_attempts",
        ["delivery_id", "started_at"],
    )
    op.create_foreign_key(
        "fk_notification_attempts_delivery_id",
        "notification_attempts",
        "notification_deliveries",
        ["delivery_id"],
        ["id"],
    )

    # Move DLQ uniqueness from job-level to delivery-level for fanout failures.
    op.add_column("notification_dead_letters", sa.Column("delivery_id", sa.String(), nullable=True))
    op.drop_constraint("uq_notification_dead_letters_job", "notification_dead_letters", type_="unique")
    op.create_foreign_key(
        "fk_notification_dead_letters_delivery_id",
        "notification_dead_letters",
        "notification_deliveries",
        ["delivery_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_notification_dead_letters_delivery",
        "notification_dead_letters",
        ["delivery_id"],
    )
    op.create_index(
        "ix_notification_dead_letters_delivery_id",
        "notification_dead_letters",
        ["delivery_id"],
    )

    # Backfill one legacy delivery row per existing job to keep in-flight rows processable after migration.
    op.execute(
        """
        INSERT INTO notification_deliveries(
            id,
            job_id,
            tenant_id,
            destination_id,
            destination,
            status,
            attempt_count,
            next_attempt_at,
            last_error,
            delivered_at,
            receipt_json,
            delivery_key,
            created_at,
            updated_at
        )
        SELECT
            md5(notification_jobs.id || '-legacy'),
            notification_jobs.id,
            notification_jobs.tenant_id,
            COALESCE(
                NULLIF(notification_jobs.payload_json->>'destination_id', ''),
                'legacy-' || md5(notification_jobs.destination)
            ) AS destination_id,
            notification_jobs.destination,
            CASE
                WHEN notification_jobs.status IN ('queued', 'delivering', 'retrying', 'delivered', 'dlq', 'skipped')
                    THEN notification_jobs.status
                ELSE 'queued'
            END AS status,
            COALESCE(notification_jobs.attempt_count, 0),
            COALESCE(notification_jobs.next_attempt_at, notification_jobs.created_at),
            notification_jobs.last_error,
            CASE WHEN notification_jobs.status = 'delivered' THEN notification_jobs.updated_at ELSE NULL END,
            NULL::jsonb,
            md5(notification_jobs.id || ':' || COALESCE(
                NULLIF(notification_jobs.payload_json->>'destination_id', ''),
                notification_jobs.destination
            )),
            notification_jobs.created_at,
            notification_jobs.updated_at
        FROM notification_jobs
        ON CONFLICT (job_id, destination_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE notification_attempts
        SET delivery_id = notification_deliveries.id
        FROM notification_deliveries
        WHERE notification_deliveries.job_id = notification_attempts.job_id
          AND notification_attempts.delivery_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE notification_dead_letters
        SET delivery_id = notification_deliveries.id
        FROM notification_deliveries
        WHERE notification_deliveries.job_id = notification_dead_letters.job_id
          AND notification_dead_letters.delivery_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_notification_dead_letters_delivery_id", table_name="notification_dead_letters")
    op.drop_constraint("uq_notification_dead_letters_delivery", "notification_dead_letters", type_="unique")
    op.drop_constraint("fk_notification_dead_letters_delivery_id", "notification_dead_letters", type_="foreignkey")
    op.create_unique_constraint("uq_notification_dead_letters_job", "notification_dead_letters", ["job_id"])
    op.drop_column("notification_dead_letters", "delivery_id")

    op.drop_constraint("fk_notification_attempts_delivery_id", "notification_attempts", type_="foreignkey")
    op.drop_index("ix_notification_attempts_delivery_started", table_name="notification_attempts")
    op.drop_column("notification_attempts", "delivery_id")

    op.drop_index("ix_notification_deliveries_delivery_key", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_destination_id", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_job_created", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_tenant_status_next", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
