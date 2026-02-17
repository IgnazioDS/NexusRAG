"""add cost governance and chargeback tables

Revision ID: 0020_cost_intel_chargeback
Revises: 0019_quality_governance
Create Date: 2026-02-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_cost_intel_chargeback"
down_revision = "0019_quality_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store request-level cost events for chargeback and budgeting.
    op.create_table(
        "usage_cost_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("route_class", sa.String(), nullable=False),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("units_json", postgresql.JSONB(), nullable=True),
        sa.Column("unit_cost_json", postgresql.JSONB(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_usage_cost_events_tenant_occurred", "usage_cost_events", ["tenant_id", "occurred_at"])
    op.create_index(
        "ix_usage_cost_events_component",
        "usage_cost_events",
        ["tenant_id", "component", "occurred_at"],
    )
    op.create_index("ix_usage_cost_events_request", "usage_cost_events", ["request_id"])

    # Persist per-tenant budget policies with optional overrides.
    op.create_table(
        "tenant_budgets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("monthly_budget_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("warn_ratio", sa.Numeric(5, 4), server_default="0.8", nullable=False),
        sa.Column("enforce_hard_cap", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("hard_cap_mode", sa.String(), server_default="block", nullable=False),
        sa.Column("current_month_override_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_budgets_tenant"),
    )
    op.create_index("ix_tenant_budgets_tenant", "tenant_budgets", ["tenant_id"])

    # Snapshot monthly budget utilization for reporting and enforcement audits.
    op.create_table(
        "tenant_budget_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column("budget_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("spend_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("forecast_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("warn_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cap_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "year_month", name="uq_budget_snapshots_month"),
    )
    op.create_index("ix_tenant_budget_snapshots_tenant", "tenant_budget_snapshots", ["tenant_id"])

    # Track active pricing rates for deterministic cost calculations.
    op.create_table(
        "pricing_catalog",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("rate_type", sa.String(), nullable=False),
        sa.Column("rate_value_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_pricing_catalog_version", "pricing_catalog", ["version"])
    op.create_index(
        "ix_pricing_catalog_provider_component_active",
        "pricing_catalog",
        ["provider", "component", "active"],
    )

    # Persist chargeback report snapshots for download/audit.
    op.create_table(
        "chargeback_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(), server_default="USD", nullable=False),
        sa.Column("total_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("breakdown_json", postgresql.JSONB(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("generated_by", sa.String(), nullable=True),
    )
    op.create_index("ix_chargeback_reports_tenant", "chargeback_reports", ["tenant_id"])

    # Seed cost governance entitlements for plan defaults.
    plan_features_table = sa.table(
        "plan_features",
        sa.column("plan_id", sa.String()),
        sa.column("feature_key", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("config_json", postgresql.JSONB()),
    )
    op.bulk_insert(
        plan_features_table,
        [
            {"plan_id": "free", "feature_key": "feature.cost_visibility", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.cost_controls", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.chargeback_reports", "enabled": False},
            {"plan_id": "pro", "feature_key": "feature.cost_visibility", "enabled": True},
            {"plan_id": "pro", "feature_key": "feature.cost_controls", "enabled": True},
            {"plan_id": "pro", "feature_key": "feature.chargeback_reports", "enabled": False},
            {"plan_id": "enterprise", "feature_key": "feature.cost_visibility", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.cost_controls", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.chargeback_reports", "enabled": True},
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM plan_features WHERE feature_key IN "
            "('feature.cost_visibility', 'feature.cost_controls', 'feature.chargeback_reports')"
        )
    )

    op.drop_index("ix_chargeback_reports_tenant", table_name="chargeback_reports")
    op.drop_table("chargeback_reports")

    op.drop_index("ix_pricing_catalog_provider_component_active", table_name="pricing_catalog")
    op.drop_index("ix_pricing_catalog_version", table_name="pricing_catalog")
    op.drop_table("pricing_catalog")

    op.drop_index("ix_tenant_budget_snapshots_tenant", table_name="tenant_budget_snapshots")
    op.drop_table("tenant_budget_snapshots")

    op.drop_index("ix_tenant_budgets_tenant", table_name="tenant_budgets")
    op.drop_table("tenant_budgets")

    op.drop_index("ix_usage_cost_events_request", table_name="usage_cost_events")
    op.drop_index("ix_usage_cost_events_component", table_name="usage_cost_events")
    op.drop_index("ix_usage_cost_events_tenant_occurred", table_name="usage_cost_events")
    op.drop_table("usage_cost_events")
