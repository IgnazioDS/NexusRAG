"""add tenant encryption and key management tables

Revision ID: 0015_tenant_encryption_keys
Revises: 0014_governance_compliance
Create Date: 2026-02-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_tenant_encryption_keys"
down_revision = "0014_governance_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Track tenant-scoped key versions for envelope encryption.
    op.create_table(
        "tenant_keys",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("key_alias", sa.String(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("key_ref", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_tenant_keys_tenant_id", "tenant_keys", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_keys_status", "tenant_keys", ["status"], unique=False)
    op.create_index(
        "ix_tenant_keys_tenant_status_version",
        "tenant_keys",
        ["tenant_id", "status", sa.text("key_version DESC")],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_tenant_keys_version",
        "tenant_keys",
        ["tenant_id", "key_alias", "key_version"],
    )

    # Store encrypted payload metadata for sensitive artifacts.
    op.create_table(
        "encrypted_blobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("key_id", sa.BigInteger(), sa.ForeignKey("tenant_keys.id"), nullable=False),
        sa.Column("wrapped_dek", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("cipher_text", sa.Text(), nullable=False),
        sa.Column("aad_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checksum_sha256", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_encrypted_blobs_tenant_id", "encrypted_blobs", ["tenant_id"], unique=False)
    op.create_index("ix_encrypted_blobs_resource_type", "encrypted_blobs", ["resource_type"], unique=False)
    op.create_index("ix_encrypted_blobs_resource_id", "encrypted_blobs", ["resource_id"], unique=False)
    op.create_index(
        "ix_encrypted_blobs_tenant_resource",
        "encrypted_blobs",
        ["tenant_id", "resource_type", "resource_id"],
        unique=False,
    )

    # Track re-encryption jobs for key rotations.
    op.create_table(
        "key_rotation_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("from_key_id", sa.BigInteger(), nullable=False),
        sa.Column("to_key_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_key_rotation_jobs_tenant_id", "key_rotation_jobs", ["tenant_id"], unique=False)
    op.create_index("ix_key_rotation_jobs_status", "key_rotation_jobs", ["status"], unique=False)
    op.create_index(
        "ix_key_rotation_jobs_tenant_status_created",
        "key_rotation_jobs",
        ["tenant_id", "status", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_key_rotation_jobs_tenant_status_created", table_name="key_rotation_jobs")
    op.drop_index("ix_key_rotation_jobs_status", table_name="key_rotation_jobs")
    op.drop_index("ix_key_rotation_jobs_tenant_id", table_name="key_rotation_jobs")
    op.drop_table("key_rotation_jobs")

    op.drop_index("ix_encrypted_blobs_tenant_resource", table_name="encrypted_blobs")
    op.drop_index("ix_encrypted_blobs_resource_id", table_name="encrypted_blobs")
    op.drop_index("ix_encrypted_blobs_resource_type", table_name="encrypted_blobs")
    op.drop_index("ix_encrypted_blobs_tenant_id", table_name="encrypted_blobs")
    op.drop_table("encrypted_blobs")

    op.drop_constraint("uq_tenant_keys_version", "tenant_keys", type_="unique")
    op.drop_index("ix_tenant_keys_tenant_status_version", table_name="tenant_keys")
    op.drop_index("ix_tenant_keys_status", table_name="tenant_keys")
    op.drop_index("ix_tenant_keys_tenant_id", table_name="tenant_keys")
    op.drop_table("tenant_keys")
