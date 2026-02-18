"""add platform key activation timestamp for keyring lifecycle contracts

Revision ID: 0027_security_contracts
Revises: 0026_notify_destinations
Create Date: 2026-02-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027_security_contracts"
down_revision = "0026_notify_destinations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Track key activation separately from creation for staged rollouts and retirement audits.
    op.add_column("platform_keys", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE platform_keys SET activated_at = created_at WHERE activated_at IS NULL")
    op.create_index("ix_platform_keys_activated_at", "platform_keys", ["activated_at"])


def downgrade() -> None:
    op.drop_index("ix_platform_keys_activated_at", table_name="platform_keys")
    op.drop_column("platform_keys", "activated_at")
