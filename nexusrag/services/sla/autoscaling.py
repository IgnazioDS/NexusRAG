from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import AutoscalingAction, AutoscalingProfile
from nexusrag.services.audit import record_event


class AutoscalingCooldownError(RuntimeError):
    # Signal cooldown conflicts so APIs can return stable 409 responses.
    pass


class AutoscalingExecutorUnavailableError(RuntimeError):
    # Signal executor backend misconfiguration/unavailability for 503 responses.
    pass


@dataclass(frozen=True)
class AutoscalingSignal:
    # Capture normalized inputs used by recommendation logic.
    route_class: str
    current_replicas: int
    p95_ms: float | None
    queue_depth: int | None
    signal_quality: str


@dataclass(frozen=True)
class AutoscalingRecommendation:
    # Return deterministic scaling outputs for dry-run/apply endpoints.
    action: str
    from_replicas: int
    to_replicas: int
    reason: str
    cooldown_active: bool
    signal_json: dict[str, Any]


class AutoscalingExecutor(Protocol):
    # Abstract executor keeps future infra integration isolated from policy logic.
    async def apply(self, recommendation: AutoscalingRecommendation) -> bool:
        ...


class NoopAutoscalingExecutor:
    async def apply(self, recommendation: AutoscalingRecommendation) -> bool:
        # No-op executor records intent without mutating infrastructure.
        return recommendation.action in {"scale_up", "scale_down", "degrade", "hold"}


def _utc_now() -> datetime:
    # Use UTC timestamps for cooldown math and persisted action records.
    return datetime.now(timezone.utc)


async def get_executor() -> AutoscalingExecutor:
    # Resolve executor backend from config while preserving deterministic fallback.
    settings = get_settings()
    if settings.autoscaling_executor == "noop":
        return NoopAutoscalingExecutor()
    raise AutoscalingExecutorUnavailableError("Autoscaling executor backend unavailable")


async def get_latest_profile_action(
    *,
    session: AsyncSession,
    profile_id: str,
) -> AutoscalingAction | None:
    # Fetch latest action per profile for cooldown and hysteresis checks.
    result = await session.execute(
        select(AutoscalingAction)
        .where(AutoscalingAction.profile_id == profile_id)
        .order_by(AutoscalingAction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _cooldown_active(*, profile: AutoscalingProfile, last_action: AutoscalingAction | None, now: datetime) -> bool:
    # Enforce cooldown windows after a scaling change to avoid oscillation.
    if last_action is None:
        return False
    if last_action.action == "hold":
        return False
    reference_time = last_action.executed_at or last_action.created_at
    if reference_time is None:
        return False
    return now < (reference_time + timedelta(seconds=max(0, profile.cooldown_seconds)))


def _recommend(
    *,
    profile: AutoscalingProfile,
    signal: AutoscalingSignal,
    hysteresis_pct: int,
    cooldown_active: bool,
) -> AutoscalingRecommendation:
    # Compute scale decisions with hysteresis and safe min/max bounds.
    hysteresis = max(0.0, float(hysteresis_pct) / 100.0)
    max_p95 = float(profile.target_p95_ms) * (1.0 + hysteresis)
    min_p95 = float(profile.target_p95_ms) * (1.0 - hysteresis)
    max_qd = float(profile.target_queue_depth) * (1.0 + hysteresis)
    min_qd = float(profile.target_queue_depth) * (1.0 - hysteresis)

    action = "hold"
    to_replicas = int(signal.current_replicas)
    reason = "within_targets"

    if signal.p95_ms is None and signal.queue_depth is None:
        reason = "signal_unavailable"
    elif cooldown_active:
        reason = "cooldown_active"
    else:
        high_latency = signal.p95_ms is not None and signal.p95_ms > max_p95
        high_queue = signal.queue_depth is not None and signal.queue_depth > max_qd
        low_latency = signal.p95_ms is not None and signal.p95_ms < min_p95
        low_queue = signal.queue_depth is not None and signal.queue_depth < min_qd

        if high_latency or high_queue:
            if signal.current_replicas < profile.max_replicas:
                action = "scale_up"
                to_replicas = min(profile.max_replicas, signal.current_replicas + max(1, profile.step_up))
                reason = "above_target"
            else:
                action = "degrade"
                to_replicas = signal.current_replicas
                reason = "at_max_replicas"
        elif low_latency and low_queue and signal.current_replicas > profile.min_replicas:
            action = "scale_down"
            to_replicas = max(profile.min_replicas, signal.current_replicas - max(1, profile.step_down))
            reason = "below_target"

    return AutoscalingRecommendation(
        action=action,
        from_replicas=signal.current_replicas,
        to_replicas=to_replicas,
        reason=reason,
        cooldown_active=cooldown_active,
        signal_json={
            "route_class": signal.route_class,
            "p95_ms": signal.p95_ms,
            "queue_depth": signal.queue_depth,
            "signal_quality": signal.signal_quality,
            "target_p95_ms": profile.target_p95_ms,
            "target_queue_depth": profile.target_queue_depth,
            "hysteresis_pct": hysteresis_pct,
        },
    )


async def evaluate_autoscaling(
    *,
    session: AsyncSession,
    profile: AutoscalingProfile,
    tenant_id: str | None,
    signal: AutoscalingSignal,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None = None,
) -> AutoscalingRecommendation:
    # Produce deterministic dry-run recommendations and persist action traces.
    settings = get_settings()
    now = _utc_now()
    last_action = await get_latest_profile_action(session=session, profile_id=profile.id)
    recommendation = _recommend(
        profile=profile,
        signal=signal,
        hysteresis_pct=settings.autoscaling_hysteresis_pct,
        cooldown_active=_cooldown_active(profile=profile, last_action=last_action, now=now),
    )
    action_row = AutoscalingAction(
        id=uuid4().hex,
        profile_id=profile.id,
        tenant_id=tenant_id,
        route_class=signal.route_class,
        action=recommendation.action,
        from_replicas=recommendation.from_replicas,
        to_replicas=recommendation.to_replicas,
        reason=recommendation.reason,
        signal_json=recommendation.signal_json,
        executed=False,
        executed_at=None,
        created_at=now,
    )
    session.add(action_row)
    await session.commit()
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key" if actor_id else "system",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="sla.autoscaling.recommended",
        outcome="success",
        resource_type="autoscaling_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={
            "action_id": action_row.id,
            "action": recommendation.action,
            "from_replicas": recommendation.from_replicas,
            "to_replicas": recommendation.to_replicas,
            "reason": recommendation.reason,
            "cooldown_active": recommendation.cooldown_active,
        },
        commit=True,
        best_effort=True,
    )
    return recommendation


async def apply_autoscaling(
    *,
    session: AsyncSession,
    profile: AutoscalingProfile,
    tenant_id: str | None,
    signal: AutoscalingSignal,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None = None,
) -> AutoscalingRecommendation:
    # Apply recommendations through executor adapters with cooldown safeguards.
    settings = get_settings()
    now = _utc_now()
    last_action = await get_latest_profile_action(session=session, profile_id=profile.id)
    cooldown_active = _cooldown_active(profile=profile, last_action=last_action, now=now)
    recommendation = _recommend(
        profile=profile,
        signal=signal,
        hysteresis_pct=settings.autoscaling_hysteresis_pct,
        cooldown_active=cooldown_active,
    )
    if recommendation.cooldown_active:
        raise AutoscalingCooldownError("Autoscaling cooldown window is active")
    executor = await get_executor()
    executed = bool(await executor.apply(recommendation)) and not settings.autoscaling_dry_run

    action_row = AutoscalingAction(
        id=uuid4().hex,
        profile_id=profile.id,
        tenant_id=tenant_id,
        route_class=signal.route_class,
        action=recommendation.action,
        from_replicas=recommendation.from_replicas,
        to_replicas=recommendation.to_replicas,
        reason=recommendation.reason,
        signal_json=recommendation.signal_json,
        executed=executed,
        executed_at=now if executed else None,
        created_at=now,
    )
    session.add(action_row)
    await session.commit()
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key" if actor_id else "system",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="sla.autoscaling.applied",
        outcome="success",
        resource_type="autoscaling_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={
            "action_id": action_row.id,
            "action": recommendation.action,
            "from_replicas": recommendation.from_replicas,
            "to_replicas": recommendation.to_replicas,
            "executed": executed,
            "dry_run": settings.autoscaling_dry_run,
        },
        commit=True,
        best_effort=True,
    )
    return recommendation
