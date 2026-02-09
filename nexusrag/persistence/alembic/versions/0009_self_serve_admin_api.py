"""add self-serve admin api tables

Revision ID: 0009_self_serve_admin_api
Revises: 0008_plan_entitlements
Create Date: 2026-02-09
"""

from __future__ import annotations

import alembic.op as op
import sqlalchemy as sa


revision = "0009_self_serve_admin_api"
down_revision = "0008_plan_entitlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store tenant-initiated plan upgrade requests for workflow review.
    op.create_table(
        "plan_upgrade_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("current_plan_id", sa.String(), nullable=False),
        sa.Column("target_plan_id", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_by_actor_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_plan_upgrade_requests_tenant",
        "plan_upgrade_requests",
        ["tenant_id"],
        unique=False,
    )

    # Seed billing webhook test entitlement for existing plans (idempotent).
    op.execute(
        sa.text(
            """
            INSERT INTO plan_features (plan_id, feature_key, enabled, created_at)
            VALUES
              ('free', 'feature.billing_webhook_test', false, now()),
              ('pro', 'feature.billing_webhook_test', true, now()),
              ('enterprise', 'feature.billing_webhook_test', true, now())
            ON CONFLICT (plan_id, feature_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM plan_features
            WHERE feature_key = 'feature.billing_webhook_test'
            """
        )
    )
    op.drop_index("ix_plan_upgrade_requests_tenant", table_name="plan_upgrade_requests")
    op.drop_table("plan_upgrade_requests")
