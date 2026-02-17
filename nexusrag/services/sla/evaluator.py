from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import SlaIncident, SlaMeasurement, SlaPolicy, TenantSlaAssignment
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.sla.policy import SlaPolicyConfig, SlaPolicyValidationError, parse_policy_config
from nexusrag.services.sla.signals import LiveSignals, collect_live_signals, load_latest_measurements


@dataclass(frozen=True)
class SlaBreach:
    # Capture breached objective metadata for auditing and explainability.
    breach_type: str
    route_class: str
    actual: float
    threshold: float
    severity: str
    message: str


@dataclass(frozen=True)
class SlaDegradeActions:
    # Describe runtime mitigations to apply when enforcement chooses degrade.
    disable_audio: bool
    top_k_floor: int
    max_output_tokens: int
    provider_fallback_order: tuple[str, ...]


@dataclass(frozen=True)
class SlaEvaluationResult:
    # Return evaluator output in a shape that runtime routes can apply directly.
    policy_id: str | None
    status: str
    breaches: tuple[SlaBreach, ...]
    recommended_actions: tuple[str, ...]
    enforcement_decision: str
    window_end: datetime | None
    signal_quality: str
    policy_mode: str
    degrade_actions: SlaDegradeActions | None
    incident_id: str | None


def _utc_now() -> datetime:
    # Use UTC timestamps for deterministic window and incident timestamps.
    return datetime.now(timezone.utc)


def _merge_config(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    # Apply assignment overrides without mutating persisted base policy config.
    merged = dict(base)
    if not override:
        return merged
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _severity_for_breach(*, breach_type: str, delta: float) -> str:
    # Map objective deltas to stable severity tiers.
    if breach_type in {"availability", "saturation"} and delta >= 10:
        return "sev1"
    if delta >= 5:
        return "sev2"
    return "sev3"


def _error_budget_burn(*, measurement: SlaMeasurement | None, availability_target_pct: float) -> float | None:
    # Estimate error-budget burn from the latest 5m error rate and objective target.
    if measurement is None or measurement.request_count <= 0:
        return None
    error_rate = measurement.error_count / max(1, measurement.request_count)
    error_budget = max(0.0001, 1.0 - (availability_target_pct / 100.0))
    return error_rate / error_budget


def _evaluate_window_breaches(
    *,
    config: SlaPolicyConfig,
    route_class: str,
    measurement_1m: SlaMeasurement | None,
    measurement_5m: SlaMeasurement | None,
    live_signals: LiveSignals,
) -> tuple[list[SlaBreach], datetime | None]:
    # Evaluate objective breaches for the newest window snapshot.
    breaches: list[SlaBreach] = []
    window_end = measurement_1m.window_end if measurement_1m is not None else None
    if measurement_1m is None:
        return breaches, window_end

    availability = float(measurement_1m.availability_pct or 0)
    if availability < config.objectives.availability_min_pct:
        delta = config.objectives.availability_min_pct - availability
        breaches.append(
            SlaBreach(
                breach_type="availability",
                route_class=route_class,
                actual=availability,
                threshold=config.objectives.availability_min_pct,
                severity=_severity_for_breach(breach_type="availability", delta=delta),
                message="Availability below minimum objective",
            )
        )

    p95_limit = config.objectives.p95_ms_max.get(route_class)
    p95_value = float(measurement_1m.p95_ms or 0)
    if p95_limit is not None and p95_value > p95_limit:
        delta = p95_value - p95_limit
        breaches.append(
            SlaBreach(
                breach_type="latency",
                route_class=route_class,
                actual=p95_value,
                threshold=p95_limit,
                severity=_severity_for_breach(breach_type="latency", delta=delta / max(1.0, p95_limit) * 100.0),
                message="p95 latency above objective",
            )
        )

    p99_limit = config.objectives.p99_ms_max.get(route_class)
    p99_value = float(measurement_1m.p99_ms or 0)
    if p99_limit is not None and p99_value > p99_limit:
        delta = p99_value - p99_limit
        breaches.append(
            SlaBreach(
                breach_type="latency",
                route_class=route_class,
                actual=p99_value,
                threshold=p99_limit,
                severity=_severity_for_breach(breach_type="latency", delta=delta / max(1.0, p99_limit) * 100.0),
                message="p99 latency above objective",
            )
        )

    saturation = (
        float(measurement_1m.saturation_pct)
        if measurement_1m.saturation_pct is not None
        else live_signals.saturation_pct
    )
    if saturation is not None and saturation > config.objectives.saturation_max_pct:
        breaches.append(
            SlaBreach(
                breach_type="saturation",
                route_class=route_class,
                actual=float(saturation),
                threshold=config.objectives.saturation_max_pct,
                severity=_severity_for_breach(
                    breach_type="saturation",
                    delta=max(0.0, float(saturation) - config.objectives.saturation_max_pct),
                ),
                message="Saturation above objective",
            )
        )

    burn = _error_budget_burn(
        measurement=measurement_5m or measurement_1m,
        availability_target_pct=config.objectives.availability_min_pct,
    )
    if burn is not None and burn > config.objectives.max_error_budget_burn_5m:
        breaches.append(
            SlaBreach(
                breach_type="error_budget",
                route_class=route_class,
                actual=float(burn),
                threshold=config.objectives.max_error_budget_burn_5m,
                severity=_severity_for_breach(
                    breach_type="error_budget",
                    delta=max(0.0, (burn - config.objectives.max_error_budget_burn_5m) * 10.0),
                ),
                message="Error budget burn above objective",
            )
        )
    return breaches, window_end


def _has_breach_for_window(*, config: SlaPolicyConfig, route_class: str, measurement: SlaMeasurement) -> bool:
    # Re-run objective checks per window to compute deterministic breach streaks.
    p95_limit = config.objectives.p95_ms_max.get(route_class)
    if p95_limit is not None and float(measurement.p95_ms or 0) > p95_limit:
        return True
    p99_limit = config.objectives.p99_ms_max.get(route_class)
    if p99_limit is not None and float(measurement.p99_ms or 0) > p99_limit:
        return True
    if float(measurement.availability_pct or 0) < config.objectives.availability_min_pct:
        return True
    if measurement.saturation_pct is not None and float(measurement.saturation_pct) > config.objectives.saturation_max_pct:
        return True
    return False


def _recommended_actions(config: SlaPolicyConfig, breaches: list[SlaBreach]) -> list[str]:
    # Produce human-readable recommendation traces for admin/simulation views.
    actions: list[str] = []
    if not breaches:
        return actions
    if config.mitigation.disable_tts_first:
        actions.append("disable_tts")
    actions.append(f"reduce_top_k:{config.mitigation.reduce_top_k_floor}")
    actions.append(f"cap_output_tokens:{config.mitigation.cap_output_tokens}")
    for provider in config.mitigation.provider_fallback_order:
        actions.append(f"fallback_provider:{provider}")
    return actions


def _enforcement_decision(
    *,
    config: SlaPolicyConfig,
    status_value: str,
    breaches: list[SlaBreach],
) -> tuple[str, SlaDegradeActions | None]:
    # Map health state + policy mode to a runtime action.
    settings = get_settings()
    if status_value == "healthy":
        return "allow", None

    mode = config.enforcement.mode
    if mode == "observe":
        return "allow", None
    if mode == "warn":
        return "warn", None

    if status_value == "warning":
        return "warn", None

    breach_types = {breach.breach_type for breach in breaches}
    if "saturation" in breach_types and settings.sla_shed_enabled:
        return "shed", None

    if config.mitigation.allow_degrade:
        return (
            "degrade",
            SlaDegradeActions(
                disable_audio=config.mitigation.disable_tts_first,
                top_k_floor=config.mitigation.reduce_top_k_floor,
                max_output_tokens=config.mitigation.cap_output_tokens,
                provider_fallback_order=config.mitigation.provider_fallback_order,
            ),
        )
    if settings.sla_shed_enabled:
        return "shed", None
    return "warn", None


async def _resolve_effective_policy(
    *,
    session: AsyncSession,
    tenant_id: str,
    now: datetime,
) -> tuple[SlaPolicy | None, dict[str, Any] | None]:
    # Resolve active tenant assignment first, then fallback to global enabled policy.
    assignment_result = await session.execute(
        select(TenantSlaAssignment)
        .where(
            TenantSlaAssignment.tenant_id == tenant_id,
            TenantSlaAssignment.effective_from <= now,
            or_(TenantSlaAssignment.effective_to.is_(None), TenantSlaAssignment.effective_to > now),
        )
        .order_by(TenantSlaAssignment.effective_from.desc())
        .limit(1)
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is not None:
        policy = await session.get(SlaPolicy, assignment.policy_id)
        if policy is not None and policy.enabled:
            return policy, assignment.override_json

    global_result = await session.execute(
        select(SlaPolicy)
        .where(
            SlaPolicy.tenant_id.is_(None),
            SlaPolicy.enabled.is_(True),
        )
        .order_by(SlaPolicy.updated_at.desc())
        .limit(1)
    )
    return global_result.scalar_one_or_none(), None


async def _upsert_incident(
    *,
    session: AsyncSession,
    tenant_id: str,
    policy_id: str,
    route_class: str,
    breaches: list[SlaBreach],
    now: datetime,
) -> tuple[str, bool]:
    # Keep one open incident per tenant/policy/route and update breach timestamps.
    if not breaches:
        return "", False
    primary_breach = breaches[0]
    existing_result = await session.execute(
        select(SlaIncident)
        .where(
            SlaIncident.tenant_id == tenant_id,
            SlaIncident.policy_id == policy_id,
            SlaIncident.route_class == route_class,
            SlaIncident.status.in_(["open", "mitigating"]),
        )
        .order_by(SlaIncident.last_breach_at.desc())
        .limit(1)
    )
    incident = existing_result.scalar_one_or_none()
    if incident is None:
        incident = SlaIncident(
            id=uuid4().hex,
            tenant_id=tenant_id,
            policy_id=policy_id,
            route_class=route_class,
            breach_type=primary_breach.breach_type,
            severity=primary_breach.severity,
            status="open",
            first_breach_at=now,
            last_breach_at=now,
            details_json={
                "breaches": [
                    {
                        "type": breach.breach_type,
                        "actual": breach.actual,
                        "threshold": breach.threshold,
                        "severity": breach.severity,
                    }
                    for breach in breaches
                ]
            },
            resolved_at=None,
        )
        session.add(incident)
        await session.commit()
        return incident.id, True

    incident.last_breach_at = now
    incident.severity = primary_breach.severity
    incident.details_json = {
        "breaches": [
            {
                "type": breach.breach_type,
                "actual": breach.actual,
                "threshold": breach.threshold,
                "severity": breach.severity,
            }
            for breach in breaches
        ]
    }
    await session.commit()
    return incident.id, False


async def evaluate_tenant_sla(
    *,
    session: AsyncSession,
    tenant_id: str,
    route_class: str,
    actor_id: str | None = None,
    actor_role: str | None = None,
    request: Any | None = None,
    request_id: str | None = None,
) -> SlaEvaluationResult:
    # Evaluate current tenant/route SLA state and emit incident/breach audit trails.
    settings = get_settings()
    now = _utc_now()
    if not settings.sla_engine_enabled:
        return SlaEvaluationResult(
            policy_id=None,
            status="healthy",
            breaches=(),
            recommended_actions=(),
            enforcement_decision="allow",
            window_end=None,
            signal_quality="ok",
            policy_mode="observe",
            degrade_actions=None,
            incident_id=None,
        )

    policy, override_json = await _resolve_effective_policy(session=session, tenant_id=tenant_id, now=now)
    if policy is None:
        return SlaEvaluationResult(
            policy_id=None,
            status="healthy",
            breaches=(),
            recommended_actions=(),
            enforcement_decision="allow",
            window_end=None,
            signal_quality="degraded",
            policy_mode=settings.sla_default_enforcement_mode,
            degrade_actions=None,
            incident_id=None,
        )

    try:
        merged_config = _merge_config(policy.config_json or {}, override_json)
        config = parse_policy_config(merged_config)
    except SlaPolicyValidationError as exc:
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="sla.signal.degraded",
            outcome="failure",
            resource_type="sla_policy",
            resource_id=policy.id,
            request_id=request_id,
            metadata={"reason": "policy_invalid", "error": str(exc)},
            commit=True,
            best_effort=True,
        )
        return SlaEvaluationResult(
            policy_id=policy.id,
            status="warning",
            breaches=(),
            recommended_actions=(),
            enforcement_decision="allow",
            window_end=None,
            signal_quality="degraded",
            policy_mode="observe",
            degrade_actions=None,
            incident_id=None,
        )

    one_minute_rows = await load_latest_measurements(
        session=session,
        tenant_id=tenant_id,
        route_class=route_class,
        window_seconds=60,
        limit=max(1, config.enforcement.consecutive_windows_to_trigger),
    )
    five_minute_rows = await load_latest_measurements(
        session=session,
        tenant_id=tenant_id,
        route_class=route_class,
        window_seconds=300,
        limit=1,
    )
    live_signals = await collect_live_signals(route_class=route_class)
    latest_1m = one_minute_rows[0] if one_minute_rows else None
    latest_5m = five_minute_rows[0] if five_minute_rows else None
    breaches, window_end = _evaluate_window_breaches(
        config=config,
        route_class=route_class,
        measurement_1m=latest_1m,
        measurement_5m=latest_5m,
        live_signals=live_signals,
    )

    breach_streak = 0
    for row in one_minute_rows:
        if _has_breach_for_window(config=config, route_class=route_class, measurement=row):
            breach_streak += 1
            continue
        break

    status_value = "healthy"
    if latest_1m is None:
        status_value = "warning"
    elif breaches and breach_streak >= config.enforcement.consecutive_windows_to_trigger:
        status_value = "breached"
    elif breaches:
        status_value = "warning"

    enforcement_decision, degrade_actions = _enforcement_decision(
        config=config,
        status_value=status_value,
        breaches=breaches,
    )
    recommendations = _recommended_actions(config, breaches)
    signal_quality = live_signals.signal_quality
    incident_id: str | None = None
    request_ctx = get_request_context(request)
    if signal_quality == "degraded":
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="sla.signal.degraded",
            outcome="success",
            resource_type="sla",
            resource_id=policy.id,
            request_id=request_ctx.get("request_id"),
            ip_address=request_ctx.get("ip_address"),
            user_agent=request_ctx.get("user_agent"),
            metadata=live_signals.details,
            commit=True,
            best_effort=True,
        )

    if status_value == "breached" and breaches:
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="sla.breach.detected",
            outcome="failure",
            resource_type="sla_policy",
            resource_id=policy.id,
            request_id=request_ctx.get("request_id"),
            ip_address=request_ctx.get("ip_address"),
            user_agent=request_ctx.get("user_agent"),
            metadata={
                "route_class": route_class,
                "breach_count": len(breaches),
                "breach_types": [breach.breach_type for breach in breaches],
                "window_end": window_end.isoformat() if window_end else None,
            },
            commit=True,
            best_effort=True,
        )
        incident_id, is_new = await _upsert_incident(
            session=session,
            tenant_id=tenant_id,
            policy_id=policy.id,
            route_class=route_class,
            breaches=breaches,
            now=now,
        )
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="sla.incident.opened" if is_new else "sla.incident.updated",
            outcome="failure",
            resource_type="sla_incident",
            resource_id=incident_id,
            request_id=request_ctx.get("request_id"),
            ip_address=request_ctx.get("ip_address"),
            user_agent=request_ctx.get("user_agent"),
            metadata={
                "policy_id": policy.id,
                "route_class": route_class,
                "breach_types": [breach.breach_type for breach in breaches],
            },
            commit=True,
            best_effort=True,
        )

    return SlaEvaluationResult(
        policy_id=policy.id,
        status=status_value,
        breaches=tuple(breaches),
        recommended_actions=tuple(recommendations),
        enforcement_decision=enforcement_decision,
        window_end=window_end,
        signal_quality=signal_quality,
        policy_mode=config.enforcement.mode,
        degrade_actions=degrade_actions,
        incident_id=incident_id,
    )
