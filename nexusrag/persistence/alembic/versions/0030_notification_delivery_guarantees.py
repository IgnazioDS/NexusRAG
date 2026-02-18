"""harden notification delivery schema for secrets, payload hashes, and status normalization

Revision ID: 0030_notify_delivery_guarantees
Revises: 0029_notify_routing_dlq
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0030_notify_delivery_guarantees"
down_revision = "0029_notify_routing_dlq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist encrypted destination secrets and static headers for deterministic webhook signing contracts.
    op.add_column("notification_destinations", sa.Column("secret_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "notification_destinations",
        sa.Column("headers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute("UPDATE notification_destinations SET headers_json = '{}'::jsonb WHERE headers_json IS NULL")

    # Keep immutable attempt digests so operators can prove exactly what payload was delivered per attempt.
    op.add_column("notification_attempts", sa.Column("payload_sha256", sa.String(), nullable=True))

    # Normalize legacy job states into the strict delivery state machine vocabulary.
    op.execute("UPDATE notification_jobs SET status = 'delivering' WHERE status = 'sending'")
    op.execute("UPDATE notification_jobs SET status = 'delivered' WHERE status = 'succeeded'")
    op.execute("UPDATE notification_jobs SET status = 'dlq' WHERE status IN ('dead_lettered', 'gave_up')")
    op.execute("UPDATE notification_jobs SET status = 'retrying' WHERE status = 'failed'")


def downgrade() -> None:
    op.execute("UPDATE notification_jobs SET status = 'sending' WHERE status = 'delivering'")
    op.execute("UPDATE notification_jobs SET status = 'succeeded' WHERE status = 'delivered'")
    op.execute("UPDATE notification_jobs SET status = 'dead_lettered' WHERE status = 'dlq'")

    op.drop_column("notification_attempts", "payload_sha256")
    op.drop_column("notification_destinations", "headers_json")
    op.drop_column("notification_destinations", "secret_encrypted")
