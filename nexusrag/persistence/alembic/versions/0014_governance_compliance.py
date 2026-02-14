"""add governance compliance tables

Revision ID: 0014_governance_compliance
Revises: 0013_multi_region_failover
Create Date: 2026-02-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_governance_compliance"
down_revision = "0013_multi_region_failover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist tenant retention preferences used by lifecycle maintenance jobs.
    op.create_table(
        "retention_policies",
        sa.Column("tenant_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("messages_ttl_days", sa.Integer(), nullable=True),
        sa.Column("checkpoints_ttl_days", sa.Integer(), nullable=True),
        sa.Column("audit_ttl_days", sa.Integer(), nullable=True),
        sa.Column("documents_ttl_days", sa.Integer(), nullable=True),
        sa.Column("backups_ttl_days", sa.Integer(), nullable=True),
        sa.Column("hard_delete_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("anonymize_instead_of_delete", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Record legal hold scopes that supersede deletion workflows.
    op.create_table(
        "legal_holds",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("scope_type", sa.String(), nullable=False),
        sa.Column("scope_id", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_actor_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_legal_holds_tenant_id", "legal_holds", ["tenant_id"], unique=False)
    op.create_index("ix_legal_holds_scope_type", "legal_holds", ["scope_type"], unique=False)
    op.create_index("ix_legal_holds_is_active", "legal_holds", ["is_active"], unique=False)
    op.create_index("ix_legal_holds_tenant_active", "legal_holds", ["tenant_id", "is_active"], unique=False)
    op.create_index("ix_legal_holds_scope", "legal_holds", ["scope_type", "scope_id"], unique=False)
    op.create_index("ix_legal_holds_expires_at", "legal_holds", ["expires_at"], unique=False)

    # Track DSAR requests and execution outcomes with artifact references.
    op.create_table(
        "dsar_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("request_type", sa.String(), nullable=False),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_by_actor_id", sa.String(), nullable=True),
        sa.Column("approved_by_actor_id", sa.String(), nullable=True),
        sa.Column("artifact_uri", sa.String(), nullable=True),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_dsar_requests_tenant", "dsar_requests", ["tenant_id"], unique=False)
    op.create_index("ix_dsar_requests_status", "dsar_requests", ["status"], unique=False)
    op.create_index("ix_dsar_requests_tenant_status", "dsar_requests", ["tenant_id", "status"], unique=False)
    op.create_index("ix_dsar_requests_created_at", "dsar_requests", ["created_at"], unique=False)

    # Store policy-as-code rules for request-time governance decisions.
    op.create_table(
        "policy_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("rule_key", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("condition_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("action_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_policy_rules_tenant", "policy_rules", ["tenant_id"], unique=False)
    op.create_index("ix_policy_rules_rule_key", "policy_rules", ["rule_key"], unique=False)
    op.create_index("ix_policy_rules_priority", "policy_rules", ["priority"], unique=False)
    op.create_index("ix_policy_rules_rule_priority", "policy_rules", ["rule_key", "priority"], unique=False)

    # Keep retention run reports available for evidence endpoints.
    op.create_table(
        "governance_retention_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_actor_id", sa.String(), nullable=True),
    )
    op.create_index("ix_governance_retention_runs_tenant_id", "governance_retention_runs", ["tenant_id"], unique=False)
    op.create_index("ix_governance_retention_runs_status", "governance_retention_runs", ["status"], unique=False)
    op.create_index(
        "ix_governance_retention_runs_tenant_started",
        "governance_retention_runs",
        ["tenant_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_governance_retention_runs_tenant_started", table_name="governance_retention_runs")
    op.drop_index("ix_governance_retention_runs_status", table_name="governance_retention_runs")
    op.drop_index("ix_governance_retention_runs_tenant_id", table_name="governance_retention_runs")
    op.drop_table("governance_retention_runs")

    op.drop_index("ix_policy_rules_rule_priority", table_name="policy_rules")
    op.drop_index("ix_policy_rules_priority", table_name="policy_rules")
    op.drop_index("ix_policy_rules_rule_key", table_name="policy_rules")
    op.drop_index("ix_policy_rules_tenant", table_name="policy_rules")
    op.drop_table("policy_rules")

    op.drop_index("ix_dsar_requests_created_at", table_name="dsar_requests")
    op.drop_index("ix_dsar_requests_tenant_status", table_name="dsar_requests")
    op.drop_index("ix_dsar_requests_status", table_name="dsar_requests")
    op.drop_index("ix_dsar_requests_tenant", table_name="dsar_requests")
    op.drop_table("dsar_requests")

    op.drop_index("ix_legal_holds_expires_at", table_name="legal_holds")
    op.drop_index("ix_legal_holds_scope", table_name="legal_holds")
    op.drop_index("ix_legal_holds_tenant_active", table_name="legal_holds")
    op.drop_index("ix_legal_holds_is_active", table_name="legal_holds")
    op.drop_index("ix_legal_holds_scope_type", table_name="legal_holds")
    op.drop_index("ix_legal_holds_tenant_id", table_name="legal_holds")
    op.drop_table("legal_holds")

    op.drop_table("retention_policies")
