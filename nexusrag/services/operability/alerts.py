from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import AlertEvent, AlertRule, SlaIncident, SlaMeasurement
from nexusrag.services.audit import record_event
from nexusrag.services.ingest.queue import get_queue_depth, get_worker_heartbeat
from nexusrag.services.operability.incidents import open_incident_for_alert
from nexusrag.services.operability.notifications import send_operability_notification
from nexusrag.services.resilience import get_circuit_breaker_state
from nexusrag.services.telemetry import availability, counters_snapshot, gauges_snapshot, p95_latency


_WINDOW_SECONDS = {"5m": 300, "1h": 3600}


def _utc_now() -> datetime:
    # Keep alert event timestamps UTC for deterministic ordering and window joins.
    return datetime.now(timezone.utc)


def _severity_rank(value: str) -> int:
    normalized = value.strip().lower()
    if normalized in {"critical", "sev1"}:
        return 4
    if normalized in {"high", "sev2"}:
        return 3
    if normalized in {"medium", "sev3"}:
        return 2
    return 1


def _window_seconds(window: str) -> int:
    return _WINDOW_SECONDS.get(window, 300)


def _default_rules_for_tenant(tenant_id: str) -> list[AlertRule]:
    # Seed baseline rules so operators can evaluate alert posture without manual bootstrap.
    definitions = (
        ("slo_burn_rate", "SLO burn rate high", "high", "slo.burn_rate", "5m", {"value": 1.0}),
        ("error_rate", "Error rate spike", "high", "error.rate", "5m", {"value": 0.05}),
        ("p95_run", "Run p95 latency high", "medium", "latency.p95.run", "5m", {"value": 3000.0}),
        ("p99_run", "Run p99 latency high", "medium", "latency.p99.run", "5m", {"value": 5000.0}),
        ("queue_depth", "Ingest queue depth high", "medium", "queue.depth", "5m", {"value": 100}),
        ("worker_heartbeat", "Worker heartbeat stale", "high", "worker.heartbeat.age_s", "5m", {"value": 120}),
        ("breaker_open", "Circuit breaker open", "high", "breaker.open.count", "5m", {"value": 1}),
        ("sla_breach_streak", "SLA breach streak sustained", "high", "sla.breach.streak", "5m", {"value": 1}),
        ("sla_shed_count", "SLA shed count spike", "critical", "sla.shed.count", "5m", {"value": 1}),
        ("quota_cap_blocks", "Quota hard-cap blocks", "medium", "quota.hard_cap.blocks", "1h", {"value": 1}),
        ("rate_limit_hits", "Rate limit hit spike", "medium", "rate_limit.hit.spike", "5m", {"value": 25}),
    )
    rows: list[AlertRule] = []
    for key, name, severity, source, window, threshold in definitions:
        rows.append(
            AlertRule(
                rule_id=f"{tenant_id}:{key}",
                tenant_id=tenant_id,
                name=name,
                severity=severity,
                enabled=True,
                source=source,
                expression_json={"metric": source, "operator": "gte"},
                window=window,
                thresholds_json=threshold,
            )
        )
    return rows


def _load_seeded_metrics(*, tenant_id: str, window: str) -> dict[str, float | int] | None:
    # Allow deterministic alert evaluation in perf/test mode from committed fixture files.
    settings = get_settings()
    if not settings.perf_mode_enabled:
        return None
    fixture_path = Path("tests/perf/fixtures/alert_metrics.json")
    if not fixture_path.exists():
        return None
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    candidate = raw.get(tenant_id) if isinstance(raw, dict) else None
    if isinstance(candidate, dict):
        window_block = candidate.get(window) or candidate.get("default")
        if isinstance(window_block, dict):
            return window_block
    default_block = raw.get("default") if isinstance(raw, dict) else None
    if isinstance(default_block, dict):
        nested = default_block.get(window) or default_block
        if isinstance(nested, dict):
            return nested
    return None


async def ensure_default_alert_rules(*, session: AsyncSession, tenant_id: str) -> None:
    # Seed tenant alert rules once so patch/evaluate APIs always have a deterministic baseline.
    count = await session.scalar(
        select(func.count()).select_from(AlertRule).where(AlertRule.tenant_id == tenant_id)
    )
    if int(count or 0) > 0:
        return
    session.add_all(_default_rules_for_tenant(tenant_id))
    await session.commit()


async def list_alert_rules(*, session: AsyncSession, tenant_id: str) -> list[AlertRule]:
    # Return tenant-scoped rule registry ordered by stable identifiers.
    await ensure_default_alert_rules(session=session, tenant_id=tenant_id)
    rows = (
        await session.execute(
            select(AlertRule)
            .where(AlertRule.tenant_id == tenant_id)
            .order_by(AlertRule.severity.desc(), AlertRule.rule_id.asc())
        )
    ).scalars().all()
    return list(rows)


async def patch_alert_rule(
    *,
    session: AsyncSession,
    tenant_id: str,
    rule_id: str,
    enabled: bool | None = None,
    severity: str | None = None,
    window: str | None = None,
    thresholds_json: dict[str, Any] | None = None,
) -> AlertRule | None:
    # Restrict edits to tenant-owned rules so cross-tenant policy drift is impossible.
    row = await session.get(AlertRule, rule_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    if enabled is not None:
        row.enabled = bool(enabled)
    if severity is not None:
        row.severity = severity
    if window is not None:
        row.window = window
    if thresholds_json is not None:
        row.thresholds_json = thresholds_json
    await session.commit()
    await session.refresh(row)
    return row


async def _collect_metrics(
    *,
    session: AsyncSession,
    tenant_id: str,
    window: str,
) -> dict[str, float | int]:
    seeded = _load_seeded_metrics(tenant_id=tenant_id, window=window)
    if seeded is not None:
        return seeded

    seconds = _window_seconds(window)
    counters = counters_snapshot()
    gauges = gauges_snapshot()
    availability_pct = availability(seconds)
    error_rate = 0.0 if availability_pct is None else max(0.0, 1.0 - (availability_pct / 100.0))
    error_budget = max(0.0001, 1.0 - (get_settings().slo_availability_target / 100.0))
    slo_burn_rate = error_rate / error_budget
    p95_run = float(p95_latency(seconds, path_prefix="/v1/run") or 0.0)
    latest_measurement = (
        await session.execute(
            select(SlaMeasurement)
            .where(SlaMeasurement.tenant_id == tenant_id, SlaMeasurement.route_class == "run")
            .order_by(SlaMeasurement.window_end.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    p99_run = float(latest_measurement.p99_ms or 0.0) if latest_measurement is not None else 0.0
    queue_depth = int(await get_queue_depth() or 0)
    worker_heartbeat = await get_worker_heartbeat()
    heartbeat_age = int((_utc_now() - worker_heartbeat).total_seconds()) if worker_heartbeat else 10_000
    breaker_states = await _breaker_open_count()
    breach_streak = await _sla_breach_streak(session=session, tenant_id=tenant_id)
    return {
        "slo.burn_rate": round(float(slo_burn_rate), 4),
        "error.rate": round(float(error_rate), 4),
        "latency.p95.run": p95_run,
        "latency.p99.run": p99_run,
        "queue.depth": queue_depth,
        "worker.heartbeat.age_s": heartbeat_age,
        "breaker.open.count": breaker_states,
        "sla.breach.streak": breach_streak,
        "sla.shed.count": int(counters.get("sla_shed_total", 0)),
        "quota.hard_cap.blocks": int(counters.get("quota_exceeded_total", 0)),
        "rate_limit.hit.spike": int(counters.get("rate_limited_total", 0)),
        "saturation.run_pct": int(gauges.get("sla.saturation_pct.run", 0)),
    }


async def _breaker_open_count() -> int:
    # Normalize breaker state checks into a single stable count metric.
    names = ("retrieval.aws_bedrock", "retrieval.gcp_vertex", "tts.openai", "billing.webhook")
    states = [await get_circuit_breaker_state(name) for name in names]
    return sum(1 for state in states if state == "open")


async def _sla_breach_streak(*, session: AsyncSession, tenant_id: str) -> int:
    # Treat each unresolved SLA incident as an active breach streak proxy for alerting.
    value = await session.scalar(
        select(func.count())
        .select_from(SlaIncident)
        .where(
            SlaIncident.tenant_id == tenant_id,
            SlaIncident.status.in_(["open", "mitigating"]),
        )
    )
    return int(value or 0)


def _compare(*, operator: str, actual: float, threshold: float) -> bool:
    if operator == "gt":
        return actual > threshold
    if operator == "gte":
        return actual >= threshold
    if operator == "lt":
        return actual < threshold
    if operator == "lte":
        return actual <= threshold
    return actual >= threshold


def _evaluate_single_rule(rule: AlertRule, metrics: dict[str, float | int]) -> tuple[bool, float, float, str]:
    # Keep alert expression support minimal and deterministic to avoid evaluator ambiguity.
    metric_key = str((rule.expression_json or {}).get("metric") or rule.source)
    operator = str((rule.expression_json or {}).get("operator") or "gte").lower()
    threshold = float((rule.thresholds_json or {}).get("value", 0.0))
    actual = float(metrics.get(metric_key, 0.0))
    triggered = _compare(operator=operator, actual=actual, threshold=threshold)
    reason = f"{metric_key} {operator} {threshold} (actual={actual})"
    return triggered, actual, threshold, reason


async def evaluate_alert_rules(
    *,
    session: AsyncSession,
    tenant_id: str,
    window: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> list[dict[str, Any]]:
    # Evaluate enabled rules and persist both triggered and suppressed outcomes for audit completeness.
    settings = get_settings()
    if not settings.alerting_enabled:
        return []
    await ensure_default_alert_rules(session=session, tenant_id=tenant_id)
    metrics = await _collect_metrics(session=session, tenant_id=tenant_id, window=window)
    rules = (
        await session.execute(
            select(AlertRule).where(
                AlertRule.tenant_id == tenant_id,
                AlertRule.enabled.is_(True),
            )
        )
    ).scalars().all()

    triggered_rows: list[dict[str, Any]] = []
    minimum_incident_severity = _severity_rank(settings.incident_auto_open_min_severity)
    for rule in rules:
        triggered, actual, threshold, reason = _evaluate_single_rule(rule, metrics)
        event = AlertEvent(
            id=uuid4().hex,
            tenant_id=tenant_id,
            rule_id=rule.rule_id,
            severity=rule.severity,
            status="triggered" if triggered else "suppressed",
            source=rule.source,
            triggered=triggered,
            metrics_json={"actual": actual, "threshold": threshold, "window": window},
            reason=reason,
            occurred_at=_utc_now(),
        )
        session.add(event)
        await session.commit()

        event_name = "alert.triggered" if triggered else "alert.suppressed"
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type=event_name,
            outcome="failure" if triggered else "success",
            resource_type="alert_rule",
            resource_id=rule.rule_id,
            request_id=request_id,
            metadata={"source": rule.source, "reason": reason},
            commit=True,
            best_effort=True,
        )
        if not triggered:
            continue

        incident_id: str | None = None
        if settings.incident_automation_enabled and _severity_rank(rule.severity) >= minimum_incident_severity:
            incident, _created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category=rule.source,
                rule_id=rule.rule_id,
                severity=rule.severity,
                title=rule.name,
                summary=reason,
                details_json={"metrics": event.metrics_json, "window": window},
                actor_id=actor_id,
                actor_role=actor_role,
                request_id=request_id,
            )
            incident_id = incident.id
        await send_operability_notification(
            session=session,
            tenant_id=tenant_id,
            event_type="alert.triggered",
            payload={"rule_id": rule.rule_id, "severity": rule.severity, "reason": reason},
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
        )
        triggered_rows.append(
            {
                "event_id": event.id,
                "rule_id": rule.rule_id,
                "name": rule.name,
                "severity": rule.severity,
                "source": rule.source,
                "status": event.status,
                "reason": reason,
                "actual": actual,
                "threshold": threshold,
                "incident_id": incident_id,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            }
        )
    return triggered_rows


async def trigger_runtime_alert(
    *,
    session: AsyncSession,
    tenant_id: str,
    source: str,
    severity: str,
    title: str,
    summary: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
    details_json: dict[str, Any] | None = None,
) -> str | None:
    # Allow runtime hooks (shed/degrade) to emit alert+incident flows without running full rule scans.
    settings = get_settings()
    if not settings.alerting_enabled:
        return None
    await ensure_default_alert_rules(session=session, tenant_id=tenant_id)
    matching = (
        await session.execute(
            select(AlertRule).where(
                AlertRule.tenant_id == tenant_id,
                AlertRule.source == source,
                AlertRule.enabled.is_(True),
            )
        )
    ).scalars().first()
    if matching is None:
        # Ensure FK integrity by creating a deterministic runtime rule when no tenant rule matches.
        matching = AlertRule(
            rule_id=f"{tenant_id}:runtime:{source}",
            tenant_id=tenant_id,
            name=f"Runtime signal: {source}",
            severity=severity,
            enabled=True,
            source=source,
            expression_json={"metric": source, "operator": "gte"},
            window="5m",
            thresholds_json={"value": 1},
        )
        session.add(matching)
        await session.commit()
    rule_id = matching.rule_id
    event = AlertEvent(
        id=uuid4().hex,
        tenant_id=tenant_id,
        rule_id=rule_id,
        severity=severity,
        status="triggered",
        source=source,
        triggered=True,
        metrics_json=details_json or {},
        reason=summary,
        occurred_at=_utc_now(),
    )
    session.add(event)
    await session.commit()
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="system",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="alert.triggered",
        outcome="failure",
        resource_type="alert_rule",
        resource_id=rule_id,
        request_id=request_id,
        metadata={"source": source, "reason": summary},
        commit=True,
        best_effort=True,
    )
    if not settings.incident_automation_enabled:
        return None
    incident, _created = await open_incident_for_alert(
        session=session,
        tenant_id=tenant_id,
        category=source,
        rule_id=matching.rule_id,
        severity=severity,
        title=title,
        summary=summary,
        details_json=details_json,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
    )
    return incident.id
