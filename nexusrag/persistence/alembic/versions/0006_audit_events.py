"""add audit events table

Revision ID: 0006_audit_events
Revises: 0005_auth_rbac
Create Date: 2026-02-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_audit_events"
down_revision = "0005_auth_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist structured audit events for auth and data mutation traceability.
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("actor_role", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"], unique=False)
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"], unique=False)
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"], unique=False)
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"], unique=False)
    op.create_index(
        "ix_audit_events_tenant_occurred_at",
        "audit_events",
        ["tenant_id", sa.text("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_event_type_occurred_at",
        "audit_events",
        ["event_type", sa.text("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_outcome_occurred_at",
        "audit_events",
        ["outcome", sa.text("occurred_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_outcome_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
