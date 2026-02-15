from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    ApiKey,
    AuditEvent,
    BackupJob,
    ComplianceArtifact,
    ControlCatalog,
    ControlEvaluation,
    ControlMapping,
    RestoreDrill,
)
from nexusrag.services.audit import record_event
from nexusrag.services.failover import get_failover_status
from nexusrag.services.governance import governance_status_snapshot
from nexusrag.services.telemetry import availability, counters_snapshot, gauges_snapshot


STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_ERROR = "error"
STATUS_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ControlEvaluationResult:
    control_id: str
    status: str
    score: int | None
    evaluated_at: datetime
    findings: dict[str, Any]
    evidence_refs: dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _window_bounds(window_days: int) -> tuple[datetime, datetime]:
    end = _utc_now()
    start = end - timedelta(days=window_days)
    return start, end


def _severity_to_status(severity: str) -> str:
    # Map lower-severity failures to warnings for SOC 2 posture summaries.
    if severity in {"low", "medium"}:
        return STATUS_WARN
    return STATUS_FAIL


def _resolve_path(data: Any, path: str | None) -> Any:
    if path is None:
        return data
    current = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _apply_operator(value: Any, operator: str, threshold: Any) -> bool:
    if operator == "eq":
        return value == threshold
    if operator == "ne":
        return value != threshold
    if operator == "gt":
        return value is not None and value > threshold
    if operator == "gte":
        return value is not None and value >= threshold
    if operator == "lt":
        return value is not None and value < threshold
    if operator == "lte":
        return value is not None and value <= threshold
    if operator == "in":
        return value in (threshold or [])
    if operator == "not_in":
        return value not in (threshold or [])
    return False


def _aggregate_value(data: Any, condition: dict[str, Any], window_seconds: int) -> Any:
    aggregation = condition.get("aggregation")
    if not aggregation:
        return _resolve_path(data, condition.get("value_path"))
    if aggregation == "count":
        if isinstance(data, dict) and "count" in data:
            return data["count"]
        if isinstance(data, list):
            return len(data)
        return int(data or 0)
    if aggregation == "rate":
        count = _aggregate_value(data, {"aggregation": "count"}, window_seconds)
        return (count / window_seconds) if window_seconds > 0 else 0.0
    if aggregation == "pct_change":
        if isinstance(data, dict) and "current" in data and "previous" in data:
            previous = max(1, int(data["previous"]))
            return ((int(data["current"]) - int(data["previous"])) / previous) * 100.0
        return 0.0
    if aggregation == "exists":
        if isinstance(data, dict) and "count" in data:
            return bool(data["count"])
        return bool(data)
    if aggregation == "latest":
        return _resolve_path(data, condition.get("value_path"))
    return _resolve_path(data, condition.get("value_path"))


def _evaluate_condition(condition: dict[str, Any], data: Any, window_seconds: int) -> tuple[bool, dict[str, Any]]:
    if "all" in condition:
        results = []
        for item in condition.get("all") or []:
            passed, detail = _evaluate_condition(item, data, window_seconds)
            results.append(detail)
            if not passed:
                return False, {"type": "all", "results": results}
        return True, {"type": "all", "results": results}
    if "any" in condition:
        results = []
        for item in condition.get("any") or []:
            passed, detail = _evaluate_condition(item, data, window_seconds)
            results.append(detail)
            if passed:
                return True, {"type": "any", "results": results}
        return False, {"type": "any", "results": results}

    operator = condition.get("operator", "eq")
    threshold = condition.get("threshold")
    value = _aggregate_value(data, condition, window_seconds)
    passed = _apply_operator(value, operator, threshold)
    return passed, {"operator": operator, "threshold": threshold, "value": value}


async def _audit_count(
    session: AsyncSession,
    *,
    tenant_scope: str | None,
    event_type: str,
    window_start: datetime,
    window_end: datetime,
) -> int:
    query = select(func.count()).select_from(AuditEvent).where(
        AuditEvent.event_type == event_type,
        AuditEvent.occurred_at >= window_start,
        AuditEvent.occurred_at <= window_end,
    )
    if tenant_scope is not None:
        query = query.where(AuditEvent.tenant_id == tenant_scope)
    return int((await session.execute(query)).scalar() or 0)


async def _signal_audit_event(
    session: AsyncSession,
    *,
    mapping: ControlMapping,
    tenant_scope: str | None,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    condition = mapping.condition_json or {}
    aggregation = condition.get("aggregation")
    if aggregation == "pct_change":
        current = await _audit_count(
            session,
            tenant_scope=tenant_scope,
            event_type=mapping.signal_ref,
            window_start=window_start,
            window_end=window_end,
        )
        delta = window_end - window_start
        previous_start = window_start - delta
        previous = await _audit_count(
            session,
            tenant_scope=tenant_scope,
            event_type=mapping.signal_ref,
            window_start=previous_start,
            window_end=window_start,
        )
        return {"current": current, "previous": previous}
    count = await _audit_count(
        session,
        tenant_scope=tenant_scope,
        event_type=mapping.signal_ref,
        window_start=window_start,
        window_end=window_end,
    )
    return {"count": count}


async def _signal_db_query(
    session: AsyncSession,
    *,
    mapping: ControlMapping,
    tenant_scope: str | None,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    # Support simple policy queries with explicit query keys.
    if mapping.signal_ref == "stale_api_keys":
        max_age_days = int(mapping.condition_json.get("max_age_days", 90))
        cutoff = window_end - timedelta(days=max_age_days)
        query = select(func.count()).select_from(ApiKey).where(
            ApiKey.revoked_at.is_(None),
            ApiKey.created_at <= cutoff,
        )
        if tenant_scope is not None:
            query = query.where(ApiKey.tenant_id == tenant_scope)
        count = int((await session.execute(query)).scalar() or 0)
        return {"count": count}
    raise ValueError(f"Unknown db_query signal_ref: {mapping.signal_ref}")


def _signal_metric(mapping: ControlMapping) -> dict[str, Any]:
    counters = counters_snapshot()
    gauges = gauges_snapshot()
    if mapping.signal_ref in counters:
        return {"value": counters[mapping.signal_ref]}
    if mapping.signal_ref in gauges:
        return {"value": gauges[mapping.signal_ref]}
    raise ValueError(f"Metric not found: {mapping.signal_ref}")


async def _slo_snapshot() -> dict[str, Any]:
    availability_1h = availability(3600)
    status = "unknown"
    settings = get_settings()
    if availability_1h is None:
        status = "unknown"
    elif availability_1h < settings.slo_availability_target:
        status = "breached"
    else:
        status = "healthy"
    return {
        "availability": availability_1h,
        "status": status,
    }


async def _dr_readiness(session: AsyncSession) -> dict[str, Any]:
    last_backup = (
        await session.execute(
            select(BackupJob)
            .where(BackupJob.status == "succeeded")
            .order_by(BackupJob.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_drill = (
        await session.execute(
            select(RestoreDrill)
            .order_by(RestoreDrill.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "backup": {
            "last_success_at": last_backup.completed_at.isoformat() if last_backup else None,
            "last_status": last_backup.status if last_backup else "unknown",
        },
        "restore_drill": {
            "last_result": last_drill.status if last_drill else "unknown",
            "last_drill_at": last_drill.completed_at.isoformat() if last_drill else None,
        },
    }


async def _governance_status(session: AsyncSession, tenant_scope: str | None) -> dict[str, Any]:
    tenant_id = tenant_scope or "system"
    return await governance_status_snapshot(session, tenant_id)


async def _failover_status(session: AsyncSession) -> dict[str, Any]:
    return await get_failover_status(session)


async def _signal_endpoint(
    session: AsyncSession,
    *,
    mapping: ControlMapping,
    tenant_scope: str | None,
) -> dict[str, Any]:
    if mapping.signal_ref == "slo_snapshot":
        return await _slo_snapshot()
    if mapping.signal_ref == "dr_readiness":
        return await _dr_readiness(session)
    if mapping.signal_ref == "governance_status":
        return await _governance_status(session, tenant_scope)
    if mapping.signal_ref == "failover_status":
        return await _failover_status(session)
    raise ValueError(f"Unknown endpoint signal_ref: {mapping.signal_ref}")


def _signal_config(mapping: ControlMapping) -> dict[str, Any]:
    settings = get_settings()
    value = getattr(settings, mapping.signal_ref, None)
    return {"value": value}


async def _signal_artifact(
    session: AsyncSession,
    *,
    mapping: ControlMapping,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    if mapping.signal_ref == "release_traceability":
        # Treat presence of a changelog entry for current version as release evidence.
        try:
            from importlib.metadata import version

            current = version("nexusrag")
        except Exception:
            current = "unknown"
        changelog = Path("CHANGELOG.md")
        exists = changelog.exists() and (current in changelog.read_text(encoding="utf-8"))
        return {"count": 1 if exists else 0}

    if mapping.signal_ref == "dependency_scan":
        query = select(func.count()).select_from(ComplianceArtifact).where(
            ComplianceArtifact.artifact_type == "dependency_scan",
            ComplianceArtifact.created_at >= window_start,
            ComplianceArtifact.created_at <= window_end,
        )
        count = int((await session.execute(query)).scalar() or 0)
        return {"count": count}

    raise ValueError(f"Unknown artifact signal_ref: {mapping.signal_ref}")


async def _evaluate_mapping(
    session: AsyncSession,
    mapping: ControlMapping,
    *,
    tenant_scope: str | None,
    window_start: datetime,
    window_end: datetime,
) -> tuple[bool, dict[str, Any]]:
    condition = mapping.condition_json or {}
    window_seconds = int((window_end - window_start).total_seconds())
    if mapping.signal_type == "audit_event":
        data = await _signal_audit_event(
            session,
            mapping=mapping,
            tenant_scope=tenant_scope,
            window_start=window_start,
            window_end=window_end,
        )
    elif mapping.signal_type == "db_query":
        data = await _signal_db_query(
            session,
            mapping=mapping,
            tenant_scope=tenant_scope,
            window_start=window_start,
            window_end=window_end,
        )
    elif mapping.signal_type == "metric":
        data = _signal_metric(mapping)
    elif mapping.signal_type == "endpoint":
        data = await _signal_endpoint(session, mapping=mapping, tenant_scope=tenant_scope)
    elif mapping.signal_type == "config":
        data = _signal_config(mapping)
    elif mapping.signal_type == "artifact":
        data = await _signal_artifact(session, mapping=mapping, window_start=window_start, window_end=window_end)
    else:
        raise ValueError(f"Unknown signal_type: {mapping.signal_type}")

    passed, detail = _evaluate_condition(condition, data, window_seconds)
    return passed, {
        "mapping_id": mapping.id,
        "signal_type": mapping.signal_type,
        "signal_ref": mapping.signal_ref,
        "condition": condition,
        "result": detail,
        "passed": passed,
    }


async def evaluate_control(
    session: AsyncSession,
    *,
    control_id: str,
    window_days: int,
    tenant_scope: str | None = None,
) -> ControlEvaluationResult:
    settings = get_settings()
    if not settings.compliance_enabled:
        raise ValueError("Compliance evaluation is disabled")
    control = await session.get(ControlCatalog, control_id)
    if control is None:
        raise ValueError(f"Control {control_id} not found")
    if not control.enabled:
        now = _utc_now()
        return ControlEvaluationResult(
            control_id=control_id,
            status=STATUS_NOT_APPLICABLE,
            score=None,
            evaluated_at=now,
            findings={"reason": "control disabled"},
            evidence_refs={},
        )

    window_start, window_end = _window_bounds(window_days)
    mappings = (
        await session.execute(select(ControlMapping).where(ControlMapping.control_id == control_id))
    ).scalars().all()
    if not mappings:
        now = _utc_now()
        return ControlEvaluationResult(
            control_id=control_id,
            status=STATUS_NOT_APPLICABLE,
            score=None,
            evaluated_at=now,
            findings={"reason": "no mappings"},
            evidence_refs={},
        )

    failures: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    status = STATUS_PASS
    error_code = None
    error_message = None
    for mapping in mappings:
        try:
            passed, detail = await _evaluate_mapping(
                session,
                mapping,
                tenant_scope=tenant_scope,
                window_start=window_start,
                window_end=window_end,
            )
        except Exception as exc:  # noqa: BLE001
            status = STATUS_ERROR
            error_code = "COMPLIANCE_EVALUATION_FAILED"
            error_message = str(exc)
            failures.append({"mapping_id": mapping.id, "error": str(exc)})
            continue
        evidence.append(detail)
        if not passed:
            failures.append(detail)

    if status != STATUS_ERROR and failures:
        status = _severity_to_status(control.severity)

    score = None
    if status == STATUS_PASS:
        score = 100
    elif status == STATUS_WARN:
        score = 60
    elif status == STATUS_FAIL:
        score = 0

    evaluation = ControlEvaluation(
        control_id=control_id,
        tenant_scope=tenant_scope,
        status=status,
        score=score,
        evaluated_at=_utc_now(),
        window_start=window_start,
        window_end=window_end,
        findings_json={"failures": failures},
        evidence_refs_json={"mappings": evidence},
        error_code=error_code,
        error_message=error_message,
    )
    session.add(evaluation)
    await session.commit()
    await session.refresh(evaluation)

    await record_event(
        session=session,
        tenant_id=tenant_scope,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="compliance.control.evaluated",
        outcome="success",
        resource_type="control",
        resource_id=control_id,
        metadata={"status": status, "score": score},
        commit=True,
        best_effort=True,
    )
    if status in {STATUS_FAIL, STATUS_ERROR}:
        await record_event(
            session=session,
            tenant_id=tenant_scope,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type="compliance.control.failed",
            outcome="failure",
            resource_type="control",
            resource_id=control_id,
            metadata={"status": status, "score": score},
            error_code=error_code or "COMPLIANCE_EVALUATION_FAILED",
            commit=True,
            best_effort=True,
        )

    return ControlEvaluationResult(
        control_id=control_id,
        status=status,
        score=score,
        evaluated_at=evaluation.evaluated_at,
        findings=evaluation.findings_json or {},
        evidence_refs=evaluation.evidence_refs_json or {},
    )


async def evaluate_all_controls(
    session: AsyncSession,
    *,
    window_days: int,
    tenant_scope: str | None = None,
    trust_criteria: list[str] | None = None,
    control_ids: list[str] | None = None,
) -> list[ControlEvaluationResult]:
    settings = get_settings()
    if not settings.compliance_enabled:
        raise ValueError("Compliance evaluation is disabled")
    query = select(ControlCatalog).where(ControlCatalog.enabled.is_(True))
    if trust_criteria:
        query = query.where(ControlCatalog.trust_criteria.in_(trust_criteria))
    if control_ids:
        query = query.where(ControlCatalog.control_id.in_(control_ids))
    controls = (await session.execute(query.order_by(ControlCatalog.control_id))).scalars().all()
    results: list[ControlEvaluationResult] = []
    for control in controls:
        results.append(
            await evaluate_control(
                session,
                control_id=control.control_id,
                window_days=window_days,
                tenant_scope=tenant_scope,
            )
        )
    return results


async def get_latest_control_statuses(
    session: AsyncSession,
    *,
    tenant_scope: str | None = None,
) -> list[dict[str, Any]]:
    # Provide latest evaluation snapshot for compliance posture summaries.
    controls = (await session.execute(select(ControlCatalog))).scalars().all()
    rows: list[dict[str, Any]] = []
    for control in controls:
        query = (
            select(ControlEvaluation)
            .where(ControlEvaluation.control_id == control.control_id)
            .order_by(ControlEvaluation.evaluated_at.desc())
            .limit(1)
        )
        if tenant_scope is not None:
            query = query.where(ControlEvaluation.tenant_scope == tenant_scope)
        latest = (await session.execute(query)).scalar_one_or_none()
        rows.append(
            {
                "control_id": control.control_id,
                "title": control.title,
                "trust_criteria": control.trust_criteria,
                "severity": control.severity,
                "status": latest.status if latest else "unknown",
                "evaluated_at": latest.evaluated_at.isoformat() if latest else None,
            }
        )
    return rows
