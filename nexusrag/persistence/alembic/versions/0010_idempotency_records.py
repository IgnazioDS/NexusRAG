"""add idempotency records

Revision ID: 0010_idempotency_records
Revises: 0009_self_serve_admin_api
Create Date: 2026-02-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_idempotency_records"
down_revision = "0009_self_serve_admin_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Store idempotency response snapshots for safe retries.
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("idem_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_id",
            "method",
            "path",
            "idem_key",
            name="uq_idempotency_records_scope",
        ),
    )
    op.create_index(
        "ix_idempotency_records_expires_at",
        "idempotency_records",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_records_tenant",
        "idempotency_records",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_records_actor",
        "idempotency_records",
        ["actor_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_actor", table_name="idempotency_records")
    op.drop_index("ix_idempotency_records_tenant", table_name="idempotency_records")
    op.drop_index("ix_idempotency_records_expires_at", table_name="idempotency_records")
    op.drop_table("idempotency_records")
