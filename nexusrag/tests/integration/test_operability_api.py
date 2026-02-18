from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from nexusrag.apps.api import rate_limit
from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    AlertEvent,
    AlertRule,
    ApiKey,
    AuditEvent,
    AuthorizationPolicy,
    IdempotencyRecord,
    IncidentTimelineEvent,
    OpsIncident,
    OperatorAction,
    TenantPlanAssignment,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.entitlements import reset_entitlements_cache
from nexusrag.tests.utils.auth import create_test_api_key


def _apply_env(monkeypatch) -> None:
    # Keep operability integration tests deterministic with fake providers and permissive limits.
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ALERTING_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("OPS_NOTIFICATION_ADAPTER", "noop")
    monkeypatch.setenv("RL_KEY_READ_RPS", "100")
    monkeypatch.setenv("RL_KEY_READ_BURST", "200")
    monkeypatch.setenv("RL_TENANT_READ_RPS", "100")
    monkeypatch.setenv("RL_TENANT_READ_BURST", "200")
    monkeypatch.setenv("RL_KEY_MUTATION_RPS", "100")
    monkeypatch.setenv("RL_KEY_MUTATION_BURST", "200")
    monkeypatch.setenv("RL_TENANT_MUTATION_RPS", "100")
    monkeypatch.setenv("RL_TENANT_MUTATION_BURST", "200")
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()
    reset_entitlements_cache()


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped rows touched by operability APIs for deterministic isolation.
    async with SessionLocal() as session:
        await session.execute(delete(AlertEvent).where(AlertEvent.tenant_id == tenant_id))
        await session.execute(delete(IncidentTimelineEvent).where(IncidentTimelineEvent.tenant_id == tenant_id))
        await session.execute(delete(OpsIncident).where(OpsIncident.tenant_id == tenant_id))
        await session.execute(delete(OperatorAction).where(OperatorAction.tenant_id == tenant_id))
        await session.execute(delete(AlertRule).where(AlertRule.tenant_id == tenant_id))
        await session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.tenant_id == tenant_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.execute(delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id))
        await session.execute(delete(AuthorizationPolicy).where(AuthorizationPolicy.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_alert_evaluate_triggers_and_dedupes_incidents(monkeypatch) -> None:
    tenant_id = f"t-operability-alert-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    async def _metrics_stub(*, session, tenant_id, window):  # type: ignore[override]
        return {
            "slo.burn_rate": 3.0,
            "error.rate": 0.25,
            "latency.p95.run": 6000.0,
            "latency.p99.run": 8000.0,
            "queue.depth": 200,
            "worker.heartbeat.age_s": 200,
            "breaker.open.count": 2,
            "sla.breach.streak": 3,
            "sla.shed.count": 2,
            "quota.hard_cap.blocks": 1,
            "rate_limit.hit.spike": 150,
        }

    from nexusrag.services.operability import alerts as alerts_module

    monkeypatch.setattr(alerts_module, "_collect_metrics", _metrics_stub)

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/v1/admin/alerts/evaluate?window=5m", headers=headers)
            assert first.status_code == 200
            first_payload = first.json()["data"]
            assert first_payload["triggered_alerts"]

            second = await client.post("/v1/admin/alerts/evaluate?window=5m", headers=headers)
            assert second.status_code == 200

        async with SessionLocal() as session:
            incidents = (
                await session.execute(
                    select(OpsIncident).where(
                        OpsIncident.tenant_id == tenant_id,
                        OpsIncident.category == "slo.burn_rate",
                        OpsIncident.status != "resolved",
                    )
                )
            ).scalars().all()
            assert len(incidents) == 1
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_incident_endpoints_require_admin(monkeypatch) -> None:
    tenant_id = f"t-operability-rbac-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/admin/incidents", headers=headers)
            assert response.status_code == 403
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ops_actions_are_idempotent_and_audited(monkeypatch) -> None:
    tenant_id = f"t-operability-action-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    headers_with_idem = {**headers, "Idempotency-Key": "idem-ops-action-1"}
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/v1/admin/ops/actions/disable-tts", headers=headers_with_idem)
            assert first.status_code == 200
            second = await client.post("/v1/admin/ops/actions/disable-tts", headers=headers_with_idem)
            assert second.status_code == 200
            assert second.headers.get("Idempotency-Replayed") == "true"
        async with SessionLocal() as session:
            action_count = await session.scalar(
                select(func.count()).select_from(OperatorAction).where(OperatorAction.tenant_id == tenant_id)
            )
            assert int(action_count or 0) == 1
            audit_rows = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.event_type == "ops.action.disable_tts",
                    )
                )
            ).scalars().all()
            assert audit_rows
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_preflight_script_passes(monkeypatch, tmp_path: Path) -> None:
    _apply_env(monkeypatch)
    settings = get_settings()
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("REDIS_URL", settings.redis_url)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SLA_ENGINE_ENABLED", "true")
    from scripts.preflight import run_preflight

    rc = await run_preflight(output_json=str(tmp_path / "preflight.json"))
    assert rc == 0
