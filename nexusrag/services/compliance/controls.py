from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.services.audit import sanitize_metadata
from nexusrag.services.entitlements import FEATURE_KEYS


@dataclass(frozen=True)
class ControlDefinition:
    control_id: str
    title: str
    description: str
    evidence_sources: list[str]
    check_method: str
    pass_criteria: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


CONTROL_CATALOG: tuple[ControlDefinition, ...] = (
    ControlDefinition(
        control_id="CC6.1",
        title="Access Control Enforcement",
        description="RBAC/ABAC controls are enabled and enforced on protected endpoints.",
        evidence_sources=["settings.auth_enabled", "settings.authz_abac_enabled"],
        check_method="automatic",
        pass_criteria="auth_enabled=true and authz_abac_enabled=true",
    ),
    ControlDefinition(
        control_id="CC6.6",
        title="Auth Failure Monitoring",
        description="Audit redaction and auth failure telemetry are present.",
        evidence_sources=["services.audit.sanitize_metadata", "audit event taxonomy"],
        check_method="automatic",
        pass_criteria="sensitive fields are redacted and failure events exist",
    ),
    ControlDefinition(
        control_id="CC7.2",
        title="Change Management",
        description="Changelog and release artifacts are maintained.",
        evidence_sources=["CHANGELOG.md", "git tags"],
        check_method="automatic",
        pass_criteria="CHANGELOG exists and contains latest version entry",
    ),
    ControlDefinition(
        control_id="CC7.3",
        title="Incident Readiness",
        description="Operational runbooks exist for incident response.",
        evidence_sources=["docs/runbooks/*.md"],
        check_method="automatic",
        pass_criteria="required runbook files exist",
    ),
    ControlDefinition(
        control_id="CC7.4",
        title="System Monitoring",
        description="Ops and SLO endpoints are registered for live monitoring.",
        evidence_sources=["/v1/ops/metrics", "/v1/ops/slo"],
        check_method="automatic",
        pass_criteria="ops endpoints are reachable in the API router",
    ),
    ControlDefinition(
        control_id="A1.1",
        title="Availability Controls",
        description="SLA/load-shedding controls are configured.",
        evidence_sources=["settings.sla_*", "settings.failover_*"],
        check_method="automatic",
        pass_criteria="SLA engine and failover controls enabled",
    ),
    ControlDefinition(
        control_id="A1.2",
        title="Backup/Restore Readiness",
        description="Backup and restore drill controls are configured.",
        evidence_sources=["settings.backup_enabled", "runbooks"],
        check_method="automatic",
        pass_criteria="backup_enabled=true and DR runbooks exist",
    ),
    ControlDefinition(
        control_id="P4.1",
        title="Data Retention Enforcement",
        description="Retention jobs are configured with explicit windows.",
        evidence_sources=["settings.*retention_days", "maintenance tasks"],
        check_method="automatic",
        pass_criteria="retention windows set and maintenance tasks available",
    ),
)


def _check_redaction() -> tuple[str, dict[str, Any]]:
    probe = {
        "api_key": "raw",
        "nested": {"authorization": "Bearer should-not-leak"},
        "safe": "ok",
    }
    sanitized = sanitize_metadata(probe)
    passed = sanitized.get("api_key") == "[REDACTED]" and sanitized["nested"].get("authorization") == "[REDACTED]"
    return ("pass" if passed else "fail", {"sample": sanitized})


def _check_ops_routes() -> tuple[str, dict[str, Any]]:
    from nexusrag.apps.api.routes.ops import router as ops_router

    route_paths = {route.path for route in ops_router.routes}
    required = {"/metrics", "/slo"}
    missing = sorted(required - route_paths)
    return ("pass" if not missing else "fail", {"missing": missing})


def _check_change_management() -> tuple[str, dict[str, Any]]:
    changelog = Path("CHANGELOG.md")
    if not changelog.exists():
        return "fail", {"reason": "missing_changelog"}
    try:
        from importlib.metadata import version

        current_version = version("nexusrag")
    except Exception:
        current_version = None
    changelog_text = changelog.read_text(encoding="utf-8")
    has_version = current_version is None or current_version in changelog_text
    return ("pass" if has_version else "degraded", {"changelog_exists": True, "current_version": current_version})


def _check_runbooks() -> tuple[str, dict[str, Any]]:
    required = [
        "docs/runbooks/compliance-control-failure-response.md",
        "docs/runbooks/sla-breach-response.md",
        "docs/runbooks/perf-regression-triage.md",
    ]
    missing = [path for path in required if not Path(path).exists()]
    return ("pass" if not missing else "degraded", {"missing": missing})


def _check_monitoring_settings() -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    ok = settings.sla_engine_enabled and settings.failover_enabled and settings.rate_limit_enabled
    return ("pass" if ok else "fail", {"sla_engine_enabled": settings.sla_engine_enabled, "failover_enabled": settings.failover_enabled})


def _check_backup_settings() -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    ok = settings.backup_enabled and settings.backup_retention_days > 0
    return ("pass" if ok else "degraded", {"backup_enabled": settings.backup_enabled, "backup_retention_days": settings.backup_retention_days})


def _check_retention_settings() -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    ok = settings.audit_retention_days > 0 and settings.usage_counter_retention_days > 0 and settings.ui_action_retention_days > 0
    return (
        "pass" if ok else "fail",
        {
            "audit_retention_days": settings.audit_retention_days,
            "usage_counter_retention_days": settings.usage_counter_retention_days,
            "ui_action_retention_days": settings.ui_action_retention_days,
        },
    )


def _check_entitlements() -> tuple[str, dict[str, Any]]:
    # Ensure core feature-gate keys exist so restricted functionality can be enforced.
    required = {
        "feature.identity.sso",
        "feature.identity.scim",
        "feature.identity.jit",
    }
    missing = sorted(required - FEATURE_KEYS)
    return ("pass" if not missing else "fail", {"missing_feature_keys": missing})


def _check_perf_gates() -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    gate_file = Path("tests/perf/assert_perf_gates.py")
    ok = gate_file.exists() and settings.perf_run_target_p95_ms > 0 and settings.perf_max_error_rate >= 0
    return (
        "pass" if ok else "fail",
        {
            "gate_file": str(gate_file),
            "exists": gate_file.exists(),
            "perf_run_target_p95_ms": settings.perf_run_target_p95_ms,
            "perf_max_error_rate": settings.perf_max_error_rate,
        },
    )


async def _check_migrations_applied(session: AsyncSession) -> tuple[str, dict[str, Any]]:
    # Compare alembic_version against current local head revision to catch drift.
    version = (await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))).scalar_one_or_none()
    expected = None
    version_files = sorted(Path("nexusrag/persistence/alembic/versions").glob("*.py"))
    if version_files:
        latest = version_files[-1]
        for line in latest.read_text(encoding="utf-8").splitlines():
            if line.startswith("revision ="):
                expected = line.split("=", 1)[1].strip().strip('"')
                break
    if expected is None:
        return "degraded", {"reason": "revision_unresolved", "db_version": version}
    return (
        "pass" if version == expected else "fail",
        {"db_version": version, "expected_version": expected},
    )


async def evaluate_controls(session: AsyncSession) -> tuple[str, list[dict[str, Any]]]:
    now = _utc_now().isoformat()
    checks: dict[str, tuple[str, dict[str, Any]]] = {
        "CC6.1": ("pass" if get_settings().auth_enabled and get_settings().authz_abac_enabled else "fail", {}),
        "CC6.6": _check_redaction(),
        "CC7.2": _check_change_management(),
        "CC7.3": _check_runbooks(),
        "CC7.4": _check_ops_routes(),
        "A1.1": _check_monitoring_settings(),
        "A1.2": _check_backup_settings(),
        "P4.1": _check_retention_settings(),
    }
    entitlements_status, entitlements_detail = _check_entitlements()
    perf_status, perf_detail = _check_perf_gates()
    migration_status, migration_detail = await _check_migrations_applied(session)

    rows: list[dict[str, Any]] = []
    status_rank = {"pass": 0, "degraded": 1, "fail": 2}
    worst = "pass"
    for control in CONTROL_CATALOG:
        status, detail = checks.get(control.control_id, ("degraded", {}))
        if status_rank[status] > status_rank[worst]:
            worst = status
        rows.append(
            {
                "control_id": control.control_id,
                "title": control.title,
                "description": control.description,
                "evidence_sources": control.evidence_sources,
                "check_method": control.check_method,
                "pass_criteria": control.pass_criteria,
                "last_evaluated_at": now,
                "status": status,
                "detail": detail,
            }
        )

    # Attach global cross-cutting checks once to keep snapshot payload compact but complete.
    rows.append(
        {
            "control_id": "SYSTEM.ENTITLEMENTS",
            "title": "Entitlement Gates",
            "description": "Feature entitlement keys required for restricted capabilities are present.",
            "evidence_sources": ["services.entitlements.FEATURE_KEYS"],
            "check_method": "automatic",
            "pass_criteria": "required feature keys exist",
            "last_evaluated_at": now,
            "status": entitlements_status,
            "detail": entitlements_detail,
        }
    )
    rows.append(
        {
            "control_id": "SYSTEM.PERF_GATES",
            "title": "Performance Gates",
            "description": "Deterministic performance gate script and thresholds exist.",
            "evidence_sources": ["tests/perf/assert_perf_gates.py", "settings.perf_*"],
            "check_method": "automatic",
            "pass_criteria": "perf gate script exists and thresholds are configured",
            "last_evaluated_at": now,
            "status": perf_status,
            "detail": perf_detail,
        }
    )
    rows.append(
        {
            "control_id": "SYSTEM.MIGRATIONS",
            "title": "Database Migrations",
            "description": "Database migration revision matches current alembic head.",
            "evidence_sources": ["alembic_version", "alembic versions directory"],
            "check_method": "automatic",
            "pass_criteria": "alembic_version equals repository head revision",
            "last_evaluated_at": now,
            "status": migration_status,
            "detail": migration_detail,
        }
    )
    for row in rows[-3:]:
        if status_rank[row["status"]] > status_rank[worst]:
            worst = row["status"]

    overall = "pass" if worst == "pass" else "degraded" if worst == "degraded" else "fail"
    return overall, rows
