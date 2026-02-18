"""add tenant notification destination routing table

Revision ID: 0026_notify_destinations
Revises: 0025_operability_notify
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0026_notify_destinations"
down_revision = "0025_operability_notify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist tenant-scoped notification destinations to avoid global-only routing behavior.
    op.create_table(
        "notification_destinations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("destination_url", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "destination_url", name="uq_notification_destinations_tenant_url"),
    )
    op.create_index("ix_notification_destinations_tenant_id", "notification_destinations", ["tenant_id"])
    op.create_index("ix_notification_destinations_enabled", "notification_destinations", ["enabled"])
    op.create_index(
        "ix_notification_destinations_tenant_enabled",
        "notification_destinations",
        ["tenant_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_destinations_tenant_enabled", table_name="notification_destinations")
    op.drop_index("ix_notification_destinations_enabled", table_name="notification_destinations")
    op.drop_index("ix_notification_destinations_tenant_id", table_name="notification_destinations")
    op.drop_table("notification_destinations")
