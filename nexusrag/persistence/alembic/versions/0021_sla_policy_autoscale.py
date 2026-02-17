"""add sla policy and autoscaling control-plane tables

Revision ID: 0021_sla_policy_autoscale
Revises: 0020_cost_intel_chargeback
Create Date: 2026-02-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_sla_policy_autoscale"
down_revision = "0020_cost_intel_chargeback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store tenant/global SLA policy definitions with versioned configs.
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", "version", name="uq_sla_policies_tenant_name_version"),
    )
    op.create_index("ix_sla_policies_tenant", "sla_policies", ["tenant_id"])

    # Assign one active policy per tenant with optional temporary overrides.
    op.create_table(
        "tenant_sla_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), sa.ForeignKey("sla_policies.id"), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_sla_assignments_tenant"),
    )
    op.create_index("ix_tenant_sla_assignments_tenant", "tenant_sla_assignments", ["tenant_id"])

    # Persist rolling SLA measurements used by runtime enforcement and incidenting.
    op.create_table(
        "sla_measurements",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("route_class", sa.String(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("p50_ms", sa.Float(), nullable=True),
        sa.Column("p95_ms", sa.Float(), nullable=True),
        sa.Column("p99_ms", sa.Float(), nullable=True),
        sa.Column("availability_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("saturation_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_sla_measurements_tenant_route_window_end",
        "sla_measurements",
        ["tenant_id", "route_class", "window_end"],
    )

    # Track SLA incidents and their mitigation lifecycle for auditability.
    op.create_table(
        "sla_incidents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), sa.ForeignKey("sla_policies.id"), nullable=False),
        sa.Column("route_class", sa.String(), nullable=False),
        sa.Column("breach_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("first_breach_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_breach_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sla_incidents_tenant", "sla_incidents", ["tenant_id"])

    # Define autoscaling profiles used for recommendation and apply flows.
    op.create_table(
        "autoscaling_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("route_class", sa.String(), nullable=True),
        sa.Column("min_replicas", sa.Integer(), nullable=False),
        sa.Column("max_replicas", sa.Integer(), nullable=False),
        sa.Column("target_p95_ms", sa.Integer(), nullable=False),
        sa.Column("target_queue_depth", sa.Integer(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("step_up", sa.Integer(), nullable=False),
        sa.Column("step_down", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_autoscaling_profiles_tenant", "autoscaling_profiles", ["tenant_id"])

    # Record autoscaling recommendations and applied actions for postmortems.
    op.create_table(
        "autoscaling_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("autoscaling_profiles.id"), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("route_class", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("from_replicas", sa.Integer(), nullable=False),
        sa.Column("to_replicas", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("signal_json", postgresql.JSONB(), nullable=True),
        sa.Column("executed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_autoscaling_actions_tenant", "autoscaling_actions", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_autoscaling_actions_tenant", table_name="autoscaling_actions")
    op.drop_table("autoscaling_actions")

    op.drop_index("ix_autoscaling_profiles_tenant", table_name="autoscaling_profiles")
    op.drop_table("autoscaling_profiles")

    op.drop_index("ix_sla_incidents_tenant", table_name="sla_incidents")
    op.drop_table("sla_incidents")

    op.drop_index("ix_sla_measurements_tenant_route_window_end", table_name="sla_measurements")
    op.drop_table("sla_measurements")

    op.drop_index("ix_tenant_sla_assignments_tenant", table_name="tenant_sla_assignments")
    op.drop_table("tenant_sla_assignments")

    op.drop_index("ix_sla_policies_tenant", table_name="sla_policies")
    op.drop_table("sla_policies")
