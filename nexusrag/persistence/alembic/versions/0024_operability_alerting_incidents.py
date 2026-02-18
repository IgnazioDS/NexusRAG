"""add alerting, incidents, and operator action control-plane tables

Revision ID: 0024_operability_alerting
Revises: 0023_security_compliance
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0024_operability_alerting"
down_revision = "0023_security_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist editable alert rules so operators can tune thresholds without code deploys.
    op.create_table(
        "alert_rules",
        sa.Column("rule_id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("expression_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("window", sa.String(), nullable=False, server_default="5m"),
        sa.Column("thresholds_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_alert_rules_tenant", "alert_rules", ["tenant_id"])
    op.create_index("ix_alert_rules_source", "alert_rules", ["source"])
    op.create_index("ix_alert_rules_severity", "alert_rules", ["severity"])
    op.create_index("ix_alert_rules_tenant_enabled", "alert_rules", ["tenant_id", "enabled"])

    # Capture every evaluation result to support incident dedupe and trend analysis.
    op.create_table(
        "alert_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("rule_id", sa.String(), sa.ForeignKey("alert_rules.rule_id"), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("triggered", sa.Boolean(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_alert_events_tenant", "alert_events", ["tenant_id"])
    op.create_index("ix_alert_events_rule", "alert_events", ["rule_id"])
    op.create_index("ix_alert_events_status", "alert_events", ["status"])
    op.create_index("ix_alert_events_tenant_occurred", "alert_events", ["tenant_id", "occurred_at"])
    op.create_index("ix_alert_events_rule_occurred", "alert_events", ["rule_id", "occurred_at"])

    # Track incident lifecycle states with stable dedupe keys per tenant/category/rule context.
    op.create_table(
        "ops_incidents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("rule_id", sa.String(), sa.ForeignKey("alert_rules.rule_id"), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(), nullable=True),
        sa.Column("assigned_to", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_ops_incidents_tenant", "ops_incidents", ["tenant_id"])
    op.create_index("ix_ops_incidents_category", "ops_incidents", ["category"])
    op.create_index("ix_ops_incidents_status", "ops_incidents", ["status"])
    op.create_index("ix_ops_incidents_dedupe_key", "ops_incidents", ["dedupe_key"])
    op.create_index("ix_ops_incidents_tenant_status_opened", "ops_incidents", ["tenant_id", "status", "opened_at"])

    # Append immutable timeline records for ack/assign/resolve and automation actions.
    op.create_table(
        "incident_timeline_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("incident_id", sa.String(), sa.ForeignKey("ops_incidents.id"), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_incident_timeline_incident", "incident_timeline_events", ["incident_id"])
    op.create_index("ix_incident_timeline_tenant", "incident_timeline_events", ["tenant_id"])
    op.create_index(
        "ix_incident_timeline_incident_created",
        "incident_timeline_events",
        ["incident_id", "created_at"],
    )

    # Persist operator actions with idempotency scopes so retries remain safe and traceable.
    op.create_table(
        "operator_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("request_json", postgresql.JSONB(), nullable=True),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "requested_by",
            "action_type",
            "idempotency_key",
            name="uq_operator_actions_idempotency",
        ),
    )
    op.create_index("ix_operator_actions_tenant", "operator_actions", ["tenant_id"])
    op.create_index("ix_operator_actions_action_type", "operator_actions", ["action_type"])
    op.create_index("ix_operator_actions_status", "operator_actions", ["status"])
    op.create_index("ix_operator_actions_requested_by", "operator_actions", ["requested_by"])
    op.create_index("ix_operator_actions_tenant_requested", "operator_actions", ["tenant_id", "requested_at"])


def downgrade() -> None:
    op.drop_index("ix_operator_actions_tenant_requested", table_name="operator_actions")
    op.drop_index("ix_operator_actions_requested_by", table_name="operator_actions")
    op.drop_index("ix_operator_actions_status", table_name="operator_actions")
    op.drop_index("ix_operator_actions_action_type", table_name="operator_actions")
    op.drop_index("ix_operator_actions_tenant", table_name="operator_actions")
    op.drop_table("operator_actions")

    op.drop_index("ix_incident_timeline_incident_created", table_name="incident_timeline_events")
    op.drop_index("ix_incident_timeline_tenant", table_name="incident_timeline_events")
    op.drop_index("ix_incident_timeline_incident", table_name="incident_timeline_events")
    op.drop_table("incident_timeline_events")

    op.drop_index("ix_ops_incidents_tenant_status_opened", table_name="ops_incidents")
    op.drop_index("ix_ops_incidents_dedupe_key", table_name="ops_incidents")
    op.drop_index("ix_ops_incidents_status", table_name="ops_incidents")
    op.drop_index("ix_ops_incidents_category", table_name="ops_incidents")
    op.drop_index("ix_ops_incidents_tenant", table_name="ops_incidents")
    op.drop_table("ops_incidents")

    op.drop_index("ix_alert_events_rule_occurred", table_name="alert_events")
    op.drop_index("ix_alert_events_tenant_occurred", table_name="alert_events")
    op.drop_index("ix_alert_events_status", table_name="alert_events")
    op.drop_index("ix_alert_events_rule", table_name="alert_events")
    op.drop_index("ix_alert_events_tenant", table_name="alert_events")
    op.drop_table("alert_events")

    op.drop_index("ix_alert_rules_tenant_enabled", table_name="alert_rules")
    op.drop_index("ix_alert_rules_severity", table_name="alert_rules")
    op.drop_index("ix_alert_rules_source", table_name="alert_rules")
    op.drop_index("ix_alert_rules_tenant", table_name="alert_rules")
    op.drop_table("alert_rules")
