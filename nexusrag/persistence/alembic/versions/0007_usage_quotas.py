"""add usage quota tables

Revision ID: 0007_usage_quotas
Revises: 0006_audit_events
Create Date: 2026-02-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_usage_quotas"
down_revision = "0006_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store per-tenant quota limits for billing and abuse protection.
    op.create_table(
        "plan_limits",
        sa.Column("tenant_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("daily_requests_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_requests_limit", sa.Integer(), nullable=True),
        sa.Column("daily_tokens_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_tokens_limit", sa.Integer(), nullable=True),
        sa.Column("soft_cap_ratio", sa.Float(), server_default=sa.text("0.8"), nullable=False),
        sa.Column("hard_cap_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_plan_limits_tenant_id", "plan_limits", ["tenant_id"], unique=False)

    # Track per-tenant usage counts per day/month period.
    op.create_table(
        "usage_counters",
        sa.Column("tenant_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("period_type", sa.String(), primary_key=True, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), primary_key=True, nullable=False),
        sa.Column("requests_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("estimated_tokens_count", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_usage_counters_tenant_period",
        "usage_counters",
        ["tenant_id", "period_type", "period_start"],
        unique=False,
    )

    # Deduplicate soft-cap threshold events per tenant/period/metric.
    op.create_table(
        "quota_soft_cap_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period_type", sa.String(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "period_type",
            "period_start",
            "metric",
            name="uq_quota_soft_cap_events_scope",
        ),
    )
    op.create_index(
        "ix_quota_soft_cap_events_tenant",
        "quota_soft_cap_events",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quota_soft_cap_events_tenant", table_name="quota_soft_cap_events")
    op.drop_table("quota_soft_cap_events")
    op.drop_index("ix_usage_counters_tenant_period", table_name="usage_counters")
    op.drop_table("usage_counters")
    op.drop_index("ix_plan_limits_tenant_id", table_name="plan_limits")
    op.drop_table("plan_limits")
