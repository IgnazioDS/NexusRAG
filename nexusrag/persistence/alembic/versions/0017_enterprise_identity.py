"""add enterprise identity models

Revision ID: 0017_enterprise_identity
Revises: 0016_soc2_compliance_controls
Create Date: 2026-02-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017_enterprise_identity"
down_revision = "0016_soc2_compliance_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store tenant-managed identity provider configurations.
    op.create_table(
        "identity_providers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("issuer", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_secret_ref", sa.String(), nullable=False),
        sa.Column("auth_url", sa.String(), nullable=False),
        sa.Column("token_url", sa.String(), nullable=False),
        sa.Column("jwks_url", sa.String(), nullable=False),
        sa.Column("scopes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("default_role", sa.String(), nullable=False),
        sa.Column("role_mapping_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("jit_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_identity_providers_tenant_id", "identity_providers", ["tenant_id"], unique=False)
    op.create_index(
        "ix_identity_providers_tenant_enabled",
        "identity_providers",
        ["tenant_id", "enabled"],
        unique=False,
    )

    # Track tenant-bound human identities for SSO and SCIM provisioning.
    op.create_table(
        "tenant_users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("external_subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "external_subject", name="uq_tenant_users_subject"),
    )
    op.create_index("ix_tenant_users_tenant_id", "tenant_users", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_users_tenant_email", "tenant_users", ["tenant_id", "email"], unique=False)
    op.create_index("ix_tenant_users_tenant_role", "tenant_users", ["tenant_id", "role"], unique=False)

    # Map SCIM identities to tenant users for provisioning sync.
    op.create_table(
        "scim_identities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["tenant_users.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["identity_providers.id"]),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_scim_identities_external"),
    )
    op.create_index("ix_scim_identities_tenant_id", "scim_identities", ["tenant_id"], unique=False)
    op.create_index("ix_scim_identities_user_id", "scim_identities", ["user_id"], unique=False)

    # Store SCIM groups with optional direct role bindings.
    op.create_table(
        "scim_groups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("role_binding", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scim_groups_tenant_id", "scim_groups", ["tenant_id"], unique=False)

    # Join table for SCIM group membership reconciliation.
    op.create_table(
        "scim_group_memberships",
        sa.Column("group_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["scim_groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["tenant_users.id"]),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_scim_group_memberships"),
    )

    # Persist hashed SCIM bearer tokens for provisioning APIs.
    op.create_table(
        "scim_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("token_prefix", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_scim_tokens_hash"),
    )
    op.create_index("ix_scim_tokens_tenant", "scim_tokens", ["tenant_id"], unique=False)
    op.create_index("ix_scim_tokens_hash", "scim_tokens", ["token_hash"], unique=True)

    # Store hashed SSO session tokens for revocation and observability.
    op.create_table(
        "sso_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=True),
        sa.Column("token_prefix", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["tenant_users.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["identity_providers.id"]),
        sa.UniqueConstraint("token_hash", name="uq_sso_sessions_hash"),
    )
    op.create_index("ix_sso_sessions_tenant", "sso_sessions", ["tenant_id"], unique=False)
    op.create_index("ix_sso_sessions_user", "sso_sessions", ["user_id"], unique=False)
    op.create_index("ix_sso_sessions_hash", "sso_sessions", ["token_hash"], unique=True)

    # Seed identity entitlements for new plans.
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
            {"plan_id": "free", "feature_key": "feature.identity.sso", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.identity.scim", "enabled": False},
            {"plan_id": "free", "feature_key": "feature.identity.jit", "enabled": False},
            {"plan_id": "pro", "feature_key": "feature.identity.sso", "enabled": True},
            {"plan_id": "pro", "feature_key": "feature.identity.scim", "enabled": False},
            {"plan_id": "pro", "feature_key": "feature.identity.jit", "enabled": False},
            {"plan_id": "enterprise", "feature_key": "feature.identity.sso", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.identity.scim", "enabled": True},
            {"plan_id": "enterprise", "feature_key": "feature.identity.jit", "enabled": True},
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM plan_features WHERE feature_key IN "
            "('feature.identity.sso', 'feature.identity.scim', 'feature.identity.jit')"
        )
    )
    op.drop_index("ix_sso_sessions_hash", table_name="sso_sessions")
    op.drop_index("ix_sso_sessions_user", table_name="sso_sessions")
    op.drop_index("ix_sso_sessions_tenant", table_name="sso_sessions")
    op.drop_table("sso_sessions")

    op.drop_index("ix_scim_tokens_hash", table_name="scim_tokens")
    op.drop_index("ix_scim_tokens_tenant", table_name="scim_tokens")
    op.drop_table("scim_tokens")

    op.drop_table("scim_group_memberships")
    op.drop_index("ix_scim_groups_tenant_id", table_name="scim_groups")
    op.drop_table("scim_groups")

    op.drop_index("ix_scim_identities_user_id", table_name="scim_identities")
    op.drop_index("ix_scim_identities_tenant_id", table_name="scim_identities")
    op.drop_table("scim_identities")

    op.drop_index("ix_tenant_users_tenant_role", table_name="tenant_users")
    op.drop_index("ix_tenant_users_tenant_email", table_name="tenant_users")
    op.drop_index("ix_tenant_users_tenant_id", table_name="tenant_users")
    op.drop_table("tenant_users")

    op.drop_index("ix_identity_providers_tenant_enabled", table_name="identity_providers")
    op.drop_index("ix_identity_providers_tenant_id", table_name="identity_providers")
    op.drop_table("identity_providers")
