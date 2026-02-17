"""bridge revision for quality governance chain continuity

Revision ID: 0019_quality_governance
Revises: 0018_abac_document_rls
Create Date: 2026-02-17
"""

from __future__ import annotations

revision = "0019_quality_governance"
down_revision = "0018_abac_document_rls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve an explicit revision boundary so environments stamped to 0019 can
    # safely advance to later migrations without rewriting alembic history.
    pass


def downgrade() -> None:
    # No schema objects were created in this bridge revision.
    pass
