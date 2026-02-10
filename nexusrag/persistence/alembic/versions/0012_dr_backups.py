"""add dr backup and restore drill tables

Revision ID: 0012_dr_backups
Revises: 0011_ui_actions
Create Date: 2026-02-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_dr_backups"
down_revision = "0011_ui_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Persist backup job metadata for DR readiness and auditability.
    op.create_table(
        "backup_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_scope", sa.String(), nullable=True),
        sa.Column("backup_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("manifest_uri", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_actor_id", sa.String(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_backup_jobs_status", "backup_jobs", ["status"], unique=False)
    op.create_index("ix_backup_jobs_started_at", "backup_jobs", ["started_at"], unique=False)

    # Track restore drill reports for compliance evidence and readiness status.
    op.create_table(
        "restore_drills",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rto_seconds", sa.Integer(), nullable=True),
        sa.Column("verified_manifest_uri", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_restore_drills_status", "restore_drills", ["status"], unique=False)
    op.create_index("ix_restore_drills_started_at", "restore_drills", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_restore_drills_started_at", table_name="restore_drills")
    op.drop_index("ix_restore_drills_status", table_name="restore_drills")
    op.drop_table("restore_drills")
    op.drop_index("ix_backup_jobs_started_at", table_name="backup_jobs")
    op.drop_index("ix_backup_jobs_status", table_name="backup_jobs")
    op.drop_table("backup_jobs")
