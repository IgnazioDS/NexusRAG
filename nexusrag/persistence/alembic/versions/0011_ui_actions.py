"""add ui actions table

Revision ID: 0011_ui_actions
Revises: 0010_idempotency_records
Create Date: 2026-02-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_ui_actions"
down_revision = "0010_idempotency_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist UI action state for optimistic updates and polling.
    op.create_table(
        "ui_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("request_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ui_actions_tenant_created_at",
        "ui_actions",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_ui_actions_status", "ui_actions", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ui_actions_status", table_name="ui_actions")
    op.drop_index("ix_ui_actions_tenant_created_at", table_name="ui_actions")
    op.drop_table("ui_actions")
