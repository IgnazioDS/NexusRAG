from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api import rate_limit
from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    ApiKey,
    AutoscalingAction,
    AutoscalingProfile,
    AuditEvent,
    Checkpoint,
    Corpus,
    Message,
    Session,
    SlaIncident,
    SlaMeasurement,
    SlaPolicy,
    TenantPlanAssignment,
    TenantSlaAssignment,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.entitlements import reset_entitlements_cache
from nexusrag.tests.utils.auth import create_test_api_key


def _apply_env(monkeypatch) -> None:
    # Keep SLA integration tests deterministic and fast.
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("COST_GOVERNANCE_ENABLED", "false")
    monkeypatch.setenv("SLA_ENGINE_ENABLED", "true")
    monkeypatch.setenv("SLA_SHED_ENABLED", "true")
    monkeypatch.setenv("AUTOSCALING_ENABLED", "true")
    monkeypatch.setenv("AUTOSCALING_DRY_RUN", "true")
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


def _strict_policy_config(*, allow_degrade: bool) -> dict:
    # Build strict config fixtures that trigger quickly in deterministic tests.
    return {
        "objectives": {
            "availability_min_pct": 99.0,
            "p95_ms_max": {"run": 100},
            "p99_ms_max": {"run": 150},
            "max_error_budget_burn_5m": 1.0,
            "saturation_max_pct": 95,
        },
        "enforcement": {
            "mode": "enforce",
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


async def _seed_sla_policy(
    *,
    tenant_id: str,
    config_json: dict,
) -> tuple[str, str]:
    # Seed tenant policy + assignment directly for runtime enforcement tests.
    now = datetime.now(timezone.utc)
    policy_id = uuid4().hex
    assignment_id = uuid4().hex
    async with SessionLocal() as session:
        session.add(
            SlaPolicy(
                id=policy_id,
                tenant_id=tenant_id,
                name="test-policy",
                tier="enterprise",
                enabled=True,
                config_json=config_json,
                version=1,
                created_by="test",
            )
        )
        session.add(
            TenantSlaAssignment(
                id=assignment_id,
                tenant_id=tenant_id,
                policy_id=policy_id,
                effective_from=now - timedelta(minutes=1),
                effective_to=None,
                override_json=None,
            )
        )
        await session.commit()
    return policy_id, assignment_id


async def _seed_breach_measurement(
    *,
    tenant_id: str,
    route_class: str = "run",
    p95_ms: float = 500,
    saturation_pct: float = 20,
) -> None:
    # Seed measurement windows that immediately satisfy breach conditions.
    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        session.add(
            SlaMeasurement(
                id=uuid4().hex,
                tenant_id=tenant_id,
                route_class=route_class,
                window_start=now - timedelta(seconds=60),
                window_end=now,
                request_count=10,
                error_count=0,
                p50_ms=100,
                p95_ms=p95_ms,
                p99_ms=p95_ms + 50,
                availability_pct=100,
                saturation_pct=saturation_pct,
                computed_at=now,
            )
        )
        await session.commit()


async def _seed_corpus(tenant_id: str) -> str:
    corpus_id = f"c-sla-{uuid4().hex}"
    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="SLA Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector", "top_k_default": 5}},
            )
        )
        await session.commit()
    return corpus_id


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped test rows for deterministic isolation.
    async with SessionLocal() as session:
        await session.execute(delete(AutoscalingAction).where(AutoscalingAction.tenant_id == tenant_id))
        await session.execute(delete(AutoscalingProfile).where(AutoscalingProfile.tenant_id == tenant_id))
        await session.execute(delete(SlaIncident).where(SlaIncident.tenant_id == tenant_id))
        await session.execute(delete(SlaMeasurement).where(SlaMeasurement.tenant_id == tenant_id))
        await session.execute(delete(TenantSlaAssignment).where(TenantSlaAssignment.tenant_id == tenant_id))
        await session.execute(delete(SlaPolicy).where(SlaPolicy.tenant_id == tenant_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        session_ids = select(Session.id).where(Session.tenant_id == tenant_id)
        await session.execute(delete(Checkpoint).where(Checkpoint.session_id.in_(session_ids)))
        await session.execute(delete(Message).where(Message.session_id.in_(session_ids)))
        await session.execute(delete(Session).where(Session.tenant_id == tenant_id))
        await session.execute(delete(Corpus).where(Corpus.tenant_id == tenant_id))
        await session.execute(delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_tenant_policy_assignment_emits_runtime_headers_and_degrade_event(monkeypatch) -> None:
    tenant_id = f"t-sla-degrade-{uuid4().hex}"
    _apply_env(monkeypatch)
    await _seed_sla_policy(tenant_id=tenant_id, config_json=_strict_policy_config(allow_degrade=True))
    await _seed_breach_measurement(tenant_id=tenant_id, p95_ms=900, saturation_pct=20)
    corpus_id = await _seed_corpus(tenant_id)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    async def stub_run_graph(**_kwargs):  # type: ignore[override]
        await asyncio.sleep(0)
        return {"answer": "ok", "citations": [], "checkpoint_state": {}}

    from nexusrag.apps.api.routes import run as run_module

    monkeypatch.setattr(run_module, "run_graph", stub_run_graph)

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "POST",
                "/v1/run",
                json={
                    "session_id": f"s-sla-{uuid4().hex}",
                    "corpus_id": corpus_id,
                    "message": "Hello",
                    "top_k": 5,
                    "audio": False,
                },
                headers=headers,
            ) as response:
                assert response.status_code == 200
                assert response.headers.get("X-SLA-Decision") == "degrade"
                assert response.headers.get("X-SLA-Status") == "breached"
                event_names: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_names.append(line.split(":", 1)[1].strip())
                    if line.startswith("data:"):
                        data = json.loads(line.removeprefix("data: ").strip())
                        if data.get("type") == "done":
                            break
                assert "sla.degrade.applied" in event_names
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_shed_mode_returns_503_and_sse_event(monkeypatch) -> None:
    tenant_id = f"t-sla-shed-{uuid4().hex}"
    _apply_env(monkeypatch)
    await _seed_sla_policy(tenant_id=tenant_id, config_json=_strict_policy_config(allow_degrade=False))
    await _seed_breach_measurement(tenant_id=tenant_id, p95_ms=900, saturation_pct=99)
    corpus_id = await _seed_corpus(tenant_id)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "POST",
                "/v1/run",
                json={
                    "session_id": f"s-shed-{uuid4().hex}",
                    "corpus_id": corpus_id,
                    "message": "Hello",
                    "top_k": 5,
                    "audio": False,
                },
                headers=headers,
            ) as response:
                assert response.status_code == 503
                assert response.headers.get("X-SLA-Decision") == "shed"
                first_error = None
                event_names: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_names.append(line.split(":", 1)[1].strip())
                    if line.startswith("data:"):
                        payload = json.loads(line.removeprefix("data: ").strip())
                        if payload.get("type") == "error":
                            first_error = payload
                        if payload.get("type") == "done":
                            break
                assert "sla.shed" in event_names
                assert first_error is not None
                assert first_error["data"]["code"] == "SLA_SHED_LOAD"
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_autoscaling_endpoints_persist_actions(monkeypatch) -> None:
    tenant_id = f"t-sla-auto-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_resp = await client.post(
                "/v1/admin/sla/autoscaling/profiles",
                json={
                    "name": "run-auto",
                    "scope": "tenant",
                    "tenant_id": tenant_id,
                    "route_class": "run",
                    "min_replicas": 1,
                    "max_replicas": 4,
                    "target_p95_ms": 200,
                    "target_queue_depth": 5,
                    "cooldown_seconds": 0,
                    "step_up": 1,
                    "step_down": 1,
                    "enabled": True,
                },
                headers=headers,
            )
            assert create_resp.status_code == 201
            profile_id = create_resp.json()["data"]["id"]

            eval_resp = await client.post(
                "/v1/admin/sla/autoscaling/evaluate",
                json={
                    "profile_id": profile_id,
                    "route_class": "run",
                    "current_replicas": 1,
                    "p95_ms": 500,
                    "queue_depth": 12,
                    "signal_quality": "ok",
                },
                headers=headers,
            )
            assert eval_resp.status_code == 200
            assert eval_resp.json()["data"]["action"] in {"scale_up", "degrade"}

            apply_resp = await client.post(
                "/v1/admin/sla/autoscaling/apply",
                json={
                    "profile_id": profile_id,
                    "route_class": "run",
                    "current_replicas": 2,
                    "p95_ms": 550,
                    "queue_depth": 15,
                    "signal_quality": "ok",
                },
                headers=headers,
            )
            assert apply_resp.status_code == 200

            actions_resp = await client.get("/v1/admin/sla/autoscaling/actions", headers=headers)
            assert actions_resp.status_code == 200
            assert len(actions_resp.json()["data"]["items"]) >= 2
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_incident_lifecycle_open_and_resolve(monkeypatch) -> None:
    tenant_id = f"t-sla-incident-{uuid4().hex}"
    _apply_env(monkeypatch)
    await _seed_sla_policy(tenant_id=tenant_id, config_json=_strict_policy_config(allow_degrade=False))
    await _seed_breach_measurement(tenant_id=tenant_id, p95_ms=900, saturation_pct=99)
    corpus_id = await _seed_corpus(tenant_id)
    _raw_reader, reader_headers, _reader_user, _reader_key = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )
    _raw_admin, admin_headers, _admin_user, _admin_key = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "POST",
                "/v1/run",
                json={
                    "session_id": f"s-incident-{uuid4().hex}",
                    "corpus_id": corpus_id,
                    "message": "Hello",
                    "top_k": 5,
                    "audio": False,
                },
                headers=reader_headers,
            ) as response:
                assert response.status_code == 503
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        payload = json.loads(line.removeprefix("data: ").strip())
                        if payload.get("type") == "done":
                            break

            incidents_resp = await client.get("/v1/admin/sla/incidents", headers=admin_headers)
            assert incidents_resp.status_code == 200
            incidents = incidents_resp.json()["data"]["items"]
            assert incidents
            incident_id = incidents[0]["id"]

            resolve_resp = await client.post(f"/v1/admin/sla/incidents/{incident_id}/resolve", headers=admin_headers)
            assert resolve_resp.status_code == 200
            assert resolve_resp.json()["data"]["status"] == "resolved"
            assert resolve_resp.json()["data"]["resolved_at"] is not None
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sla_admin_endpoints_are_tenant_scoped(monkeypatch) -> None:
    tenant_a = f"t-sla-a-{uuid4().hex}"
    tenant_b = f"t-sla-b-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_a, headers_a, _user_a, _key_a = await create_test_api_key(
        tenant_id=tenant_a,
        role="admin",
        plan_id="enterprise",
    )
    _raw_b, headers_b, _user_b, _key_b = await create_test_api_key(
        tenant_id=tenant_b,
        role="admin",
        plan_id="enterprise",
    )
    policy_id, _assignment_id = await _seed_sla_policy(tenant_id=tenant_a, config_json=_strict_policy_config(allow_degrade=True))
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            forbidden = await client.get(f"/v1/admin/sla/assignments/{tenant_a}", headers=headers_b)
            assert forbidden.status_code == 403

            not_found = await client.patch(
                f"/v1/admin/sla/policies/{policy_id}",
                json={"name": "x"},
                headers=headers_b,
            )
            assert not_found.status_code == 404
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
        get_settings.cache_clear()
