"""add abac policies and document permissions

Revision ID: 0018_abac_document_rls
Revises: 0017_enterprise_identity
Create Date: 2026-02-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_abac_document_rls"
down_revision = "0017_enterprise_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store ABAC policies with tenant scoping and deterministic ordering.
    op.create_table(
        "authorization_policies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("effect", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("condition_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_authz_policies_tenant_enabled_resource_action_priority",
        "authorization_policies",
        [
            "tenant_id",
            "enabled",
            "resource_type",
            "action",
            sa.text("priority DESC"),
        ],
        unique=False,
    )

    # Record explicit document-level permissions for principals.
    op.create_table(
        "document_permissions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("principal_type", sa.String(), nullable=False),
        sa.Column("principal_id", sa.String(), nullable=False),
        sa.Column("permission", sa.String(), nullable=False),
        sa.Column("granted_by", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "principal_type",
            "principal_id",
            "permission",
            name="uq_doc_permissions_principal_permission",
        ),
    )
    op.create_index(
        "ix_doc_permissions_tenant_document",
        "document_permissions",
        ["tenant_id", "document_id"],
        unique=False,
    )
    op.create_index(
        "ix_doc_permissions_tenant_principal",
        "document_permissions",
        ["tenant_id", "principal_type", "principal_id"],
        unique=False,
    )

    # Store document labels for ABAC policy evaluation.
    op.create_table(
        "document_labels",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.UniqueConstraint("tenant_id", "document_id", "key", name="uq_document_labels_key"),
    )
    op.create_index("ix_document_labels_tenant", "document_labels", ["tenant_id"], unique=False)

    # Cache computed principal attributes for ABAC evaluation.
    op.create_table(
        "principal_attributes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("principal_type", sa.String(), nullable=False),
        sa.Column("principal_id", sa.String(), nullable=False),
        sa.Column("attrs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "principal_type",
            "principal_id",
            name="uq_principal_attributes_identity",
        ),
    )
    op.create_index(
        "ix_principal_attributes_tenant",
        "principal_attributes",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_principal_attributes_tenant", table_name="principal_attributes")
    op.drop_table("principal_attributes")

    op.drop_index("ix_document_labels_tenant", table_name="document_labels")
    op.drop_table("document_labels")

    op.drop_index("ix_doc_permissions_tenant_principal", table_name="document_permissions")
    op.drop_index("ix_doc_permissions_tenant_document", table_name="document_permissions")
    op.drop_table("document_permissions")

    op.drop_index(
        "ix_authz_policies_tenant_enabled_resource_action_priority",
        table_name="authorization_policies",
    )
    op.drop_table("authorization_policies")
