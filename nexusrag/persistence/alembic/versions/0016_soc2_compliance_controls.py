"""add soc2 compliance control catalog and evidence tracking

Revision ID: 0016_soc2_compliance_controls
Revises: 0015_tenant_encryption_keys
Create Date: 2026-02-15
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_soc2_compliance_controls"
down_revision = "0015_tenant_encryption_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Define SOC 2 control catalog metadata for automated evaluations.
    op.create_table(
        "control_catalog",
        sa.Column("control_id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("trust_criteria", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_role", sa.String(), nullable=False),
        sa.Column("check_type", sa.String(), nullable=False),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_control_catalog_trust_criteria", "control_catalog", ["trust_criteria"], unique=False)

    # Map controls to measurable platform signals and evidence templates.
    op.create_table(
        "control_mappings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("control_id", sa.String(), sa.ForeignKey("control_catalog.control_id"), nullable=False),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("signal_ref", sa.String(), nullable=False),
        sa.Column("condition_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_template_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_control_mappings_control_id", "control_mappings", ["control_id"], unique=False)

    # Record evaluations for continuous control checks.
    op.create_table(
        "control_evaluations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("control_id", sa.String(), sa.ForeignKey("control_catalog.control_id"), nullable=False),
        sa.Column("tenant_scope", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("findings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence_refs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_control_evaluations_control_eval",
        "control_evaluations",
        ["control_id", sa.text("evaluated_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_control_evaluations_status_eval",
        "control_evaluations",
        ["status", sa.text("evaluated_at DESC")],
        unique=False,
    )

    # Track generated evidence bundles for SOC 2 reporting.
    op.create_table(
        "evidence_bundles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bundle_type", sa.String(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("manifest_uri", sa.String(), nullable=True),
        sa.Column("signature", sa.String(), nullable=True),
        sa.Column("checksum_sha256", sa.String(), nullable=True),
        sa.Column("generated_by_actor_id", sa.String(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_evidence_bundles_status_generated",
        "evidence_bundles",
        ["status", sa.text("generated_at DESC")],
        unique=False,
    )

    # Store manual compliance artifacts (e.g., dependency scan attestations).
    op.create_table(
        "compliance_artifacts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("control_id", sa.String(), sa.ForeignKey("control_catalog.control_id"), nullable=True),
        sa.Column("artifact_uri", sa.String(), nullable=True),
        sa.Column("checksum_sha256", sa.String(), nullable=True),
        sa.Column("created_by_actor_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_compliance_artifacts_type_created",
        "compliance_artifacts",
        ["artifact_type", sa.text("created_at DESC")],
        unique=False,
    )

    # Seed baseline SOC 2 controls and mappings.
    control_catalog = sa.table(
        "control_catalog",
        sa.column("control_id", sa.String),
        sa.column("title", sa.String),
        sa.column("trust_criteria", sa.String),
        sa.column("description", sa.Text),
        sa.column("owner_role", sa.String),
        sa.column("check_type", sa.String),
        sa.column("frequency", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("severity", sa.String),
    )
    op.bulk_insert(
        control_catalog,
        [
            {
                "control_id": "CC6.1",
                "title": "Access control enforcement",
                "trust_criteria": "security",
                "description": "Ensure access controls are enforced and failures are monitored.",
                "owner_role": "security",
                "check_type": "automated",
                "frequency": "continuous",
                "enabled": True,
                "severity": "high",
            },
            {
                "control_id": "CC6.2",
                "title": "API key governance",
                "trust_criteria": "security",
                "description": "Ensure API keys are rotated or reviewed within policy.",
                "owner_role": "security",
                "check_type": "automated",
                "frequency": "weekly",
                "enabled": True,
                "severity": "medium",
            },
            {
                "control_id": "CC7.1",
                "title": "Change management evidence",
                "trust_criteria": "availability",
                "description": "Ensure deployments are traceable to tagged releases and changelog entries.",
                "owner_role": "platform",
                "check_type": "automated",
                "frequency": "continuous",
                "enabled": True,
                "severity": "low",
            },
            {
                "control_id": "CC7.2",
                "title": "Monitoring and incident response readiness",
                "trust_criteria": "availability",
                "description": "Ensure SLO posture is healthy and monitoring remains available.",
                "owner_role": "platform",
                "check_type": "automated",
                "frequency": "continuous",
                "enabled": True,
                "severity": "high",
            },
            {
                "control_id": "CC8.1",
                "title": "Vulnerability and patch cadence",
                "trust_criteria": "security",
                "description": "Ensure dependency scans are performed within the policy window.",
                "owner_role": "security",
                "check_type": "hybrid",
                "frequency": "monthly",
                "enabled": True,
                "severity": "medium",
            },
            {
                "control_id": "A1.1",
                "title": "Backup and restore drill compliance",
                "trust_criteria": "availability",
                "description": "Ensure backups and restore drills complete successfully.",
                "owner_role": "platform",
                "check_type": "automated",
                "frequency": "weekly",
                "enabled": True,
                "severity": "high",
            },
            {
                "control_id": "C1.1",
                "title": "Encryption posture",
                "trust_criteria": "confidentiality",
                "description": "Ensure encryption is enabled and key rotations are current.",
                "owner_role": "security",
                "check_type": "automated",
                "frequency": "daily",
                "enabled": True,
                "severity": "high",
            },
        ],
    )

    control_mappings = sa.table(
        "control_mappings",
        sa.column("control_id", sa.String),
        sa.column("signal_type", sa.String),
        sa.column("signal_ref", sa.String),
        sa.column("condition_json", postgresql.JSONB),
        sa.column("evidence_template_json", postgresql.JSONB),
    )
    op.bulk_insert(
        control_mappings,
        [
            {
                "control_id": "CC6.1",
                "signal_type": "audit_event",
                "signal_ref": "rbac.forbidden",
                "condition_json": json.loads(
                    json.dumps({"aggregation": "count", "operator": "lte", "threshold": 1000})
                ),
                "evidence_template_json": json.loads(
                    json.dumps({"summary": "RBAC forbidden events within window"})
                ),
            },
            {
                "control_id": "CC6.1",
                "signal_type": "audit_event",
                "signal_ref": "auth.access.failure",
                "condition_json": json.loads(
                    json.dumps({"aggregation": "count", "operator": "lte", "threshold": 1000})
                ),
                "evidence_template_json": json.loads(
                    json.dumps({"summary": "Auth failures within window"})
                ),
            },
            {
                "control_id": "CC6.2",
                "signal_type": "db_query",
                "signal_ref": "stale_api_keys",
                "condition_json": json.loads(
                    json.dumps(
                        {
                            "aggregation": "count",
                            "operator": "eq",
                            "threshold": 0,
                            "max_age_days": 90,
                        }
                    )
                ),
                "evidence_template_json": json.loads(
                    json.dumps({"summary": "Stale active API keys older than policy"})
                ),
            },
            {
                "control_id": "CC7.1",
                "signal_type": "artifact",
                "signal_ref": "release_traceability",
                "condition_json": json.loads(
                    json.dumps({"aggregation": "exists", "operator": "eq", "threshold": True})
                ),
                "evidence_template_json": json.loads(
                    json.dumps({"summary": "Release tag and changelog traceability"})
                ),
            },
            {
                "control_id": "CC7.2",
                "signal_type": "endpoint",
                "signal_ref": "slo_snapshot",
                "condition_json": json.loads(
                    json.dumps(
                        {
                            "all": [
                                {"value_path": "status", "operator": "ne", "threshold": "breached"},
                            ]
                        }
                    )
                ),
                "evidence_template_json": json.loads(
                    json.dumps({"summary": "SLO availability status"})
                ),
            },
            {
                "control_id": "CC8.1",
                "signal_type": "artifact",
                "signal_ref": "dependency_scan",
                "condition_json": json.loads(
                    json.dumps({"aggregation": "exists", "operator": "eq", "threshold": True})
                ),
                "evidence_template_json": json.loads(
                    json.dumps({"summary": "Dependency scan artifact within policy window"})
                ),
            },
            {
                "control_id": "A1.1",
                "signal_type": "endpoint",
                "signal_ref": "dr_readiness",
                "condition_json": json.loads(
                    json.dumps(
                        {
                            "all": [
                                {"value_path": "backup.last_status", "operator": "eq", "threshold": "success"},
                                {"value_path": "restore_drill.last_result", "operator": "eq", "threshold": "passed"},
                            ]
                        }
                    )
                ),
                "evidence_template_json": json.loads(
                    json.dumps({"summary": "Backup and restore drill readiness"})
                ),
            },
            {
                "control_id": "C1.1",
                "signal_type": "endpoint",
                "signal_ref": "governance_status",
                "condition_json": json.loads(
                    json.dumps(
                        {
                            "all": [
                                {"value_path": "crypto.crypto_enabled", "operator": "eq", "threshold": True},
                                {"value_path": "crypto.overdue_rotations", "operator": "eq", "threshold": 0},
                                {"value_path": "crypto.unencrypted_sensitive_items", "operator": "eq", "threshold": 0},
                            ]
                        }
                    )
                ),
                "evidence_template_json": json.loads(
                    json.dumps({"summary": "Encryption posture compliance"})
                ),
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_artifacts_type_created", table_name="compliance_artifacts")
    op.drop_table("compliance_artifacts")

    op.drop_index("ix_evidence_bundles_status_generated", table_name="evidence_bundles")
    op.drop_table("evidence_bundles")

    op.drop_index("ix_control_evaluations_status_eval", table_name="control_evaluations")
    op.drop_index("ix_control_evaluations_control_eval", table_name="control_evaluations")
    op.drop_table("control_evaluations")

    op.drop_index("ix_control_mappings_control_id", table_name="control_mappings")
    op.drop_table("control_mappings")

    op.drop_index("ix_control_catalog_trust_criteria", table_name="control_catalog")
    op.drop_table("control_catalog")
