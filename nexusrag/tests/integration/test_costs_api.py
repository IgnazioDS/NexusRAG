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
    AuditEvent,
    ChargebackReport,
    Corpus,
    Checkpoint,
    Message,
    PricingCatalog,
    Session,
    TenantBudget,
    TenantBudgetSnapshot,
    UsageCostEvent,
    ApiKey,
    AuthorizationPolicy,
    TenantPlanAssignment,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.entitlements import reset_entitlements_cache
from nexusrag.tests.utils.auth import create_test_api_key


def _apply_env(monkeypatch, **overrides: str) -> None:
    # Keep test configuration deterministic and fast.
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("COST_GOVERNANCE_ENABLED", "true")
    monkeypatch.setenv("COST_ESTIMATOR_ENABLED", "true")
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


async def _seed_pricing(version_tag: str) -> None:
    # Seed deterministic pricing rates for cost estimates and metering.
    now = datetime.now(timezone.utc) - timedelta(days=1)
    async with SessionLocal() as session:
        session.add_all(
            [
                PricingCatalog(
                    id=uuid4().hex,
                    version=version_tag,
                    provider="internal",
                    component="retrieval",
                    rate_type="per_request",
                    rate_value_usd=1.0,
                    effective_from=now,
                    effective_to=None,
                    active=True,
                    metadata_json=None,
                ),
                PricingCatalog(
                    id=uuid4().hex,
                    version=version_tag,
                    provider="local_pgvector",
                    component="retrieval",
                    rate_type="per_request",
                    rate_value_usd=1.0,
                    effective_from=now,
                    effective_to=None,
                    active=True,
                    metadata_json=None,
                ),
                PricingCatalog(
                    id=uuid4().hex,
                    version=version_tag,
                    provider="internal",
                    component="llm",
                    rate_type="per_1k_tokens",
                    rate_value_usd=1.0,
                    effective_from=now,
                    effective_to=None,
                    active=True,
                    metadata_json=None,
                ),
                PricingCatalog(
                    id=uuid4().hex,
                    version=version_tag,
                    provider="internal",
                    component="tts",
                    rate_type="per_char",
                    rate_value_usd=0.0001,
                    effective_from=now,
                    effective_to=None,
                    active=True,
                    metadata_json=None,
                ),
                PricingCatalog(
                    id=uuid4().hex,
                    version=version_tag,
                    provider="internal",
                    component="storage",
                    rate_type="per_mb",
                    rate_value_usd=0.5,
                    effective_from=now,
                    effective_to=None,
                    active=True,
                    metadata_json=None,
                ),
                PricingCatalog(
                    id=uuid4().hex,
                    version=version_tag,
                    provider="internal",
                    component="queue",
                    rate_type="per_request",
                    rate_value_usd=0.1,
                    effective_from=now,
                    effective_to=None,
                    active=True,
                    metadata_json=None,
                ),
                PricingCatalog(
                    id=uuid4().hex,
                    version=version_tag,
                    provider="internal",
                    component="embedding",
                    rate_type="per_1k_tokens",
                    rate_value_usd=0.5,
                    effective_from=now,
                    effective_to=None,
                    active=True,
                    metadata_json=None,
                ),
            ]
        )
        await session.commit()


async def _cleanup_pricing(version_tag: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(PricingCatalog).where(PricingCatalog.version == version_tag))
        await session.commit()


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped rows to keep integration tests isolated.
    async with SessionLocal() as session:
        await session.execute(delete(ChargebackReport).where(ChargebackReport.tenant_id == tenant_id))
        await session.execute(delete(TenantBudgetSnapshot).where(TenantBudgetSnapshot.tenant_id == tenant_id))
        await session.execute(delete(TenantBudget).where(TenantBudget.tenant_id == tenant_id))
        await session.execute(delete(UsageCostEvent).where(UsageCostEvent.tenant_id == tenant_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        session_ids = select(Session.id).where(Session.tenant_id == tenant_id)
        await session.execute(delete(Checkpoint).where(Checkpoint.session_id.in_(session_ids)))
        await session.execute(delete(Message).where(Message.session_id.in_(session_ids)))
        await session.execute(delete(Session).where(Session.tenant_id == tenant_id))
        await session.execute(delete(Corpus).where(Corpus.tenant_id == tenant_id))
        await session.execute(delete(AuthorizationPolicy).where(AuthorizationPolicy.tenant_id == tenant_id))
        await session.execute(delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_run_emits_cost_headers_and_records_events(monkeypatch) -> None:
    tenant_id = f"t-cost-run-{uuid4().hex}"
    version_tag = f"test-{uuid4().hex}"
    _apply_env(monkeypatch)
    await _seed_pricing(version_tag)
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

    corpus_id = f"c-cost-{uuid4().hex}"
    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Cost Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector", "top_k_default": 5}},
            )
        )
        await session.commit()

    payload = {
        "session_id": f"s-cost-{uuid4().hex}",
        "corpus_id": corpus_id,
        "message": "Hello",
        "top_k": 5,
        "audio": False,
    }

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/v1/run", json=payload, headers=headers) as response:
                assert response.status_code == 200
                assert "X-Cost-Status" in response.headers
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data = json.loads(line.removeprefix("data: ").strip())
                        if data.get("type") == "done":
                            break
        async with SessionLocal() as session:
            count = (
                await session.execute(
                    select(UsageCostEvent).where(UsageCostEvent.tenant_id == tenant_id)
                )
            ).scalars().all()
            assert len(count) >= 2
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_pricing(version_tag)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_warn_threshold_emits_warning_event(monkeypatch) -> None:
    tenant_id = f"t-cost-warn-{uuid4().hex}"
    version_tag = f"test-{uuid4().hex}"
    _apply_env(monkeypatch)
    await _seed_pricing(version_tag)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    async with SessionLocal() as session:
        corpus_id = f"c-warn-{uuid4().hex}"
        session.add(
            TenantBudget(
                id=uuid4().hex,
                tenant_id=tenant_id,
                monthly_budget_usd=2,
                warn_ratio=0.5,
                enforce_hard_cap=False,
                hard_cap_mode="block",
                current_month_override_usd=None,
            )
        )
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Warn Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector", "top_k_default": 5}},
            )
        )
        await session.commit()

    async def stub_run_graph(**_kwargs):  # type: ignore[override]
        await asyncio.sleep(0)
        return {"answer": "ok", "citations": [], "checkpoint_state": {}}

    from nexusrag.apps.api.routes import run as run_module

    monkeypatch.setattr(run_module, "run_graph", stub_run_graph)

    payload = {
        "session_id": f"s-warn-{uuid4().hex}",
        "corpus_id": corpus_id,
        "message": "Hello",
        "top_k": 5,
        "audio": False,
    }

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/v1/run", json=payload, headers=headers) as response:
                assert response.status_code == 200
                assert response.headers.get("X-Cost-Status") == "warn"
                event_names = []
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_names.append(line.split(":", 1)[1].strip())
                    if line.startswith("data:"):
                        data = json.loads(line.removeprefix("data: ").strip())
                        if data.get("type") == "done":
                            break
                assert "cost.warn" in event_names
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_pricing(version_tag)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_hard_cap_blocks_request(monkeypatch) -> None:
    tenant_id = f"t-cost-cap-{uuid4().hex}"
    version_tag = f"test-{uuid4().hex}"
    _apply_env(monkeypatch)
    await _seed_pricing(version_tag)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    async with SessionLocal() as session:
        session.add(
            TenantBudget(
                id=uuid4().hex,
                tenant_id=tenant_id,
                monthly_budget_usd=1,
                warn_ratio=0.5,
                enforce_hard_cap=True,
                hard_cap_mode="block",
                current_month_override_usd=None,
            )
        )
        corpus_id = f"c-cap-{uuid4().hex}"
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Cap Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector", "top_k_default": 5}},
            )
        )
        await session.commit()

    payload = {
        "session_id": f"s-cap-{uuid4().hex}",
        "corpus_id": corpus_id,
        "message": "Hello",
        "top_k": 5,
        "audio": False,
    }

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/v1/run", json=payload, headers=headers) as response:
                assert response.status_code == 402
                first_error = None
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data = json.loads(line.removeprefix("data: ").strip())
                        if data.get("type") == "error":
                            first_error = data
                            break
                assert first_error is not None
                assert first_error["data"]["code"] == "COST_BUDGET_EXCEEDED"
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_pricing(version_tag)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_degrade_mode_allows_with_event(monkeypatch) -> None:
    tenant_id = f"t-cost-degrade-{uuid4().hex}"
    version_tag = f"test-{uuid4().hex}"
    _apply_env(monkeypatch)
    await _seed_pricing(version_tag)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    async with SessionLocal() as session:
        session.add(
            TenantBudget(
                id=uuid4().hex,
                tenant_id=tenant_id,
                monthly_budget_usd=1,
                warn_ratio=0.5,
                enforce_hard_cap=True,
                hard_cap_mode="degrade",
                current_month_override_usd=None,
            )
        )
        corpus_id = f"c-degrade-{uuid4().hex}"
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Degrade Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector", "top_k_default": 5}},
            )
        )
        await session.commit()

    async def stub_run_graph(**_kwargs):  # type: ignore[override]
        await asyncio.sleep(0)
        return {"answer": "ok", "citations": [], "checkpoint_state": {}}

    from nexusrag.apps.api.routes import run as run_module

    monkeypatch.setattr(run_module, "run_graph", stub_run_graph)

    payload = {
        "session_id": f"s-degrade-{uuid4().hex}",
        "corpus_id": corpus_id,
        "message": "Hello",
        "top_k": 5,
        "audio": False,
    }

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/v1/run", json=payload, headers=headers) as response:
                assert response.status_code == 200
                assert response.headers.get("X-Cost-Status") == "degraded"
                event_names = []
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event_names.append(line.split(":", 1)[1].strip())
                    if line.startswith("data:"):
                        data = json.loads(line.removeprefix("data: ").strip())
                        if data.get("type") == "done":
                            break
                assert "cost.degraded" in event_names
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_pricing(version_tag)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cost_endpoints_enforce_rbac_and_entitlements(monkeypatch) -> None:
    tenant_id = f"t-cost-free-{uuid4().hex}"
    tenant_admin = None
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="free",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/admin/costs/budget", headers=headers)
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "COST_FEATURE_NOT_ENABLED"

        tenant_admin = f"t-cost-admin-{uuid4().hex}"
        _raw_key_r, headers_r, _user_id_r, _key_id_r = await create_test_api_key(
            tenant_id=tenant_admin,
            role="reader",
            plan_id="enterprise",
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/admin/costs/budget", headers=headers_r)
            assert response.status_code == 403
    finally:
        await _cleanup_tenant(tenant_id)
        if tenant_admin is not None:
            await _cleanup_tenant(tenant_admin)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chargeback_reports_are_tenant_scoped(monkeypatch) -> None:
    tenant_a = f"t-cost-a-{uuid4().hex}"
    tenant_b = f"t-cost-b-{uuid4().hex}"
    version_tag = f"test-{uuid4().hex}"
    _apply_env(monkeypatch)
    await _seed_pricing(version_tag)
    _raw_key_a, headers_a, _user_id_a, _key_id_a = await create_test_api_key(
        tenant_id=tenant_a,
        role="admin",
        plan_id="enterprise",
    )
    _raw_key_b, headers_b, _user_id_b, _key_id_b = await create_test_api_key(
        tenant_id=tenant_b,
        role="admin",
        plan_id="enterprise",
    )

    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        session.add(
            UsageCostEvent(
                id=uuid4().hex,
                tenant_id=tenant_a,
                request_id=None,
                session_id=None,
                route_class="run",
                component="llm",
                provider="internal",
                units_json={"tokens": 100},
                unit_cost_json=None,
                cost_usd=2.5,
                occurred_at=now,
                metadata_json=None,
            )
        )
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/admin/costs/chargeback/generate",
                params={
                    "period_start": (now - timedelta(days=1)).isoformat(),
                    "period_end": (now + timedelta(days=1)).isoformat(),
                },
                headers=headers_a,
            )
            assert response.status_code == 200
            report_id = response.json()["data"]["id"]

            response = await client.get(f"/v1/admin/costs/chargeback/reports/{report_id}", headers=headers_b)
            assert response.status_code == 404
    finally:
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
        await _cleanup_pricing(version_tag)
        get_settings.cache_clear()
