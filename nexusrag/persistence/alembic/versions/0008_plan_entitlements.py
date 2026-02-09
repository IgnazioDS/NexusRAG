"""add plan-based entitlements

Revision ID: 0008_plan_entitlements
Revises: 0007_usage_quotas
Create Date: 2026-02-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_plan_entitlements"
down_revision = "0007_usage_quotas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store plan definitions for entitlement assignments.
    op.create_table(
        "plans",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_plans_active", "plans", ["is_active"], unique=False)

    # Store feature entitlements per plan, optionally with config.
    op.create_table(
        "plan_features",
        sa.Column("plan_id", sa.String(), sa.ForeignKey("plans.id"), primary_key=True),
        sa.Column("feature_key", sa.String(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("config_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_plan_features_plan_id", "plan_features", ["plan_id"], unique=False)

    # Track plan assignments with an active marker for enforcement.
    op.create_table(
        "tenant_plan_assignments",
        sa.Column("tenant_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), primary_key=True, nullable=False),
        sa.Column("plan_id", sa.String(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_tenant_plan_assignments_tenant",
        "tenant_plan_assignments",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_plan_assignments_active",
        "tenant_plan_assignments",
        ["tenant_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "uq_tenant_plan_assignments_active",
        "tenant_plan_assignments",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # Allow tenant-specific overrides to supersede plan defaults.
    op.create_table(
        "tenant_feature_overrides",
        sa.Column("tenant_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("feature_key", sa.String(), primary_key=True, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("config_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_tenant_feature_overrides_tenant",
        "tenant_feature_overrides",
        ["tenant_id"],
        unique=False,
    )

    # Seed baseline plan catalog and feature entitlements.
    op.bulk_insert(
        sa.table(
            "plans",
            sa.column("id", sa.String()),
            sa.column("name", sa.String()),
            sa.column("is_active", sa.Boolean()),
        ),
        [
            {"id": "free", "name": "Free", "is_active": True},
            {"id": "pro", "name": "Pro", "is_active": True},
            {"id": "enterprise", "name": "Enterprise", "is_active": True},
        ],
    )

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
            {"plan_id": "free", "feature_key": "feature.retrieval.local_pgvector", "enabled": True},
            {"plan_id": "free", "feature_key": "feature.retrieval.aws_bedrock", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.retrieval.gcp_vertex", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.tts", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.ops_admin_access", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.audit_access", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.high_quota_tier", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.corpora_patch_provider_config", "enabled": False},
            {"plan_id": "pro", "feature_key": "feature.retrieval.local_pgvector", "enabled": True},
            {"plan_id": "pro", "feature_key": "feature.retrieval.aws_bedrock", "enabled": False},
            {"plan_id": "pro", "feature_key": "feature.retrieval.gcp_vertex", "enabled": True},
            {"plan_id": "pro", "feature_key": "feature.tts", "enabled": True},
            {"plan_id": "pro", "feature_key": "feature.ops_admin_access", "enabled": True},
            {"plan_id": "pro", "feature_key": "feature.audit_access", "enabled": True},
            {"plan_id": "pro", "feature_key": "feature.high_quota_tier", "enabled": False},
            {"plan_id": "pro", "feature_key": "feature.corpora_patch_provider_config", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.retrieval.local_pgvector", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.retrieval.aws_bedrock", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.retrieval.gcp_vertex", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.tts", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.ops_admin_access", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.audit_access", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.high_quota_tier", "enabled": True},
            {
                "plan_id": "enterprise",
                "feature_key": "feature.corpora_patch_provider_config",
                "enabled": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_feature_overrides_tenant",
        table_name="tenant_feature_overrides",
    )
    op.drop_table("tenant_feature_overrides")
    op.drop_index(
        "uq_tenant_plan_assignments_active",
        table_name="tenant_plan_assignments",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_index(
        "ix_tenant_plan_assignments_active",
        table_name="tenant_plan_assignments",
    )
    op.drop_index(
        "ix_tenant_plan_assignments_tenant",
        table_name="tenant_plan_assignments",
    )
    op.drop_table("tenant_plan_assignments")
    op.drop_index("ix_plan_features_plan_id", table_name="plan_features")
    op.drop_table("plan_features")
    op.drop_index("ix_plans_active", table_name="plans")
    op.drop_table("plans")
