from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete

from nexusrag.domain.models import (
    AutoscalingAction,
    AutoscalingProfile,
    SlaIncident,
    SlaMeasurement,
    SlaPolicy,
    TenantSlaAssignment,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.sla.autoscaling import (
    AutoscalingCooldownError,
    AutoscalingSignal,
    apply_autoscaling,
    evaluate_autoscaling,
)
from nexusrag.services.sla.evaluator import evaluate_tenant_sla
from nexusrag.services.sla.policy import SlaPolicyValidationError, parse_policy_config


def _policy_config(*, mode: str = "enforce", allow_degrade: bool = True) -> dict:
    # Build compact SLA policy fixtures for deterministic tests.
    return {
        "objectives": {
            "availability_min_pct": 99.0,
            "p95_ms_max": {"run": 500},
            "p99_ms_max": {"run": 800},
            "max_error_budget_burn_5m": 2.0,
            "saturation_max_pct": 95,
        },
        "enforcement": {
            "mode": mode,
            "breach_window_minutes": 5,
            "consecutive_windows_to_trigger": 1,
        },
        "mitigation": {
            "allow_degrade": allow_degrade,
            "disable_tts_first": True,
            "reduce_top_k_floor": 2,
            "cap_output_tokens": 128,
            "provider_fallback_order": ["local_pgvector"],
        },
        "autoscaling_link": {"profile_id": None},
    }


@pytest.mark.asyncio
async def test_policy_parser_accepts_valid_schema() -> None:
    parsed = parse_policy_config(_policy_config())
    assert parsed.enforcement.mode == "enforce"
    assert parsed.objectives.p95_ms_max["run"] == 500
    assert parsed.mitigation.reduce_top_k_floor == 2


def test_policy_parser_rejects_invalid_schema() -> None:
    bad_config = _policy_config()
    bad_config["objectives"]["p95_ms_max"] = {"unknown": 100}
    with pytest.raises(SlaPolicyValidationError):
        parse_policy_config(bad_config)


@pytest.mark.asyncio
async def test_evaluator_decisions_healthy_warning_breached() -> None:
    tenant_id = f"t-sla-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    try:
        async with SessionLocal() as session:
            policy = SlaPolicy(
                id=uuid4().hex,
                tenant_id=tenant_id,
                name="tenant-policy",
                tier="enterprise",
                enabled=True,
                config_json=_policy_config(mode="enforce", allow_degrade=True),
                version=1,
                created_by="test",
            )
            session.add(policy)
            session.add(
                TenantSlaAssignment(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    policy_id=policy.id,
                    effective_from=now - timedelta(minutes=1),
                    effective_to=None,
                    override_json=None,
                )
            )
            await session.commit()

            healthy_row = SlaMeasurement(
                id=uuid4().hex,
                tenant_id=tenant_id,
                route_class="run",
                window_start=now - timedelta(minutes=1),
                window_end=now,
                request_count=10,
                error_count=0,
                p50_ms=100,
                p95_ms=200,
                p99_ms=300,
                availability_pct=100,
                saturation_pct=20,
                computed_at=now,
            )
            session.add(healthy_row)
            await session.commit()
            healthy = await evaluate_tenant_sla(session=session, tenant_id=tenant_id, route_class="run")
            assert healthy.status == "healthy"
            assert healthy.enforcement_decision == "allow"

            healthy_row.p95_ms = 900
            await session.commit()
            breached = await evaluate_tenant_sla(session=session, tenant_id=tenant_id, route_class="run")
            assert breached.status == "breached"
            assert breached.enforcement_decision == "degrade"

            policy.config_json = _policy_config(mode="warn", allow_degrade=True)
            await session.commit()
            warning = await evaluate_tenant_sla(session=session, tenant_id=tenant_id, route_class="run")
            assert warning.status == "breached"
            assert warning.enforcement_decision == "warn"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(SlaMeasurement).where(SlaMeasurement.tenant_id == tenant_id))
            await session.execute(delete(SlaIncident).where(SlaIncident.tenant_id == tenant_id))
            await session.execute(delete(TenantSlaAssignment).where(TenantSlaAssignment.tenant_id == tenant_id))
            await session.execute(delete(SlaPolicy).where(SlaPolicy.tenant_id == tenant_id))
            await session.commit()


@pytest.mark.asyncio
async def test_autoscaling_recommendation_and_cooldown() -> None:
    tenant_id = f"t-sla-scale-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    profile_id = uuid4().hex
    try:
        async with SessionLocal() as session:
            profile = AutoscalingProfile(
                id=profile_id,
                name="run-profile",
                scope="tenant",
                tenant_id=tenant_id,
                route_class="run",
                min_replicas=1,
                max_replicas=4,
                target_p95_ms=200,
                target_queue_depth=5,
                cooldown_seconds=600,
                step_up=1,
                step_down=1,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            session.add(profile)
            await session.commit()

            recommendation = await evaluate_autoscaling(
                session=session,
                profile=profile,
                tenant_id=tenant_id,
                signal=AutoscalingSignal(
                    route_class="run",
                    current_replicas=1,
                    p95_ms=500,
                    queue_depth=10,
                    signal_quality="ok",
                ),
                actor_id="test",
                actor_role="admin",
            )
            assert recommendation.action == "scale_up"

            with pytest.raises(AutoscalingCooldownError):
                await apply_autoscaling(
                    session=session,
                    profile=profile,
                    tenant_id=tenant_id,
                    signal=AutoscalingSignal(
                        route_class="run",
                        current_replicas=2,
                        p95_ms=450,
                        queue_depth=12,
                        signal_quality="ok",
                    ),
                    actor_id="test",
                    actor_role="admin",
                )
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AutoscalingAction).where(AutoscalingAction.tenant_id == tenant_id))
            await session.execute(delete(AutoscalingProfile).where(AutoscalingProfile.tenant_id == tenant_id))
            await session.commit()


@pytest.mark.asyncio
async def test_mitigation_transform_applies_expected_fields() -> None:
    tenant_id = f"t-sla-mitigation-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    try:
        async with SessionLocal() as session:
            policy = SlaPolicy(
                id=uuid4().hex,
                tenant_id=tenant_id,
                name="mitigation-policy",
                tier="enterprise",
                enabled=True,
                config_json=_policy_config(mode="enforce", allow_degrade=True),
                version=1,
                created_by="test",
            )
            session.add(policy)
            session.add(
                TenantSlaAssignment(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    policy_id=policy.id,
                    effective_from=now - timedelta(minutes=1),
                    effective_to=None,
                    override_json=None,
                )
            )
            session.add(
                SlaMeasurement(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    route_class="run",
                    window_start=now - timedelta(minutes=1),
                    window_end=now,
                    request_count=10,
                    error_count=0,
                    p50_ms=200,
                    p95_ms=900,
                    p99_ms=1000,
                    availability_pct=100,
                    saturation_pct=40,
                    computed_at=now,
                )
            )
            await session.commit()
            result = await evaluate_tenant_sla(session=session, tenant_id=tenant_id, route_class="run")
            assert result.enforcement_decision == "degrade"
            assert result.degrade_actions is not None
            assert result.degrade_actions.disable_audio is True
            assert result.degrade_actions.top_k_floor == 2
            assert result.degrade_actions.max_output_tokens == 128
            assert result.degrade_actions.provider_fallback_order == ("local_pgvector",)
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(SlaMeasurement).where(SlaMeasurement.tenant_id == tenant_id))
            await session.execute(delete(SlaIncident).where(SlaIncident.tenant_id == tenant_id))
            await session.execute(delete(TenantSlaAssignment).where(TenantSlaAssignment.tenant_id == tenant_id))
            await session.execute(delete(SlaPolicy).where(SlaPolicy.tenant_id == tenant_id))
            await session.commit()
