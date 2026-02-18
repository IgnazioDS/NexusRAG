from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.services.resilience import get_run_bulkhead, reset_bulkheads
from nexusrag.tests.utils.auth import create_test_api_key


@pytest.mark.asyncio
async def test_run_kill_switch_blocks() -> None:
    get_settings.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t1", role="reader")
    try:
        get_settings.cache_clear()
        from os import environ
        environ["KILL_RUN"] = "true"
        get_settings.cache_clear()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/run",
                headers=headers,
                json={"session_id": "s1", "corpus_id": "c1", "message": "hello", "top_k": 1},
            )
            assert response.status_code == 503
            payload = response.json()["error"]
            assert payload["code"] == "FEATURE_TEMPORARILY_DISABLED"
    finally:
        environ["KILL_RUN"] = "false"
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_run_bulkhead_service_busy(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MAX_CONCURRENCY", "1")
    get_settings.cache_clear()
    reset_bulkheads()
    bulkhead = get_run_bulkhead()
    lease = await bulkhead.acquire()
    assert lease is not None

    app = create_app()
    transport = ASGITransport(app=app)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t1", role="reader")
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/run",
                headers=headers,
                json={"session_id": "s2", "corpus_id": "c1", "message": "hello", "top_k": 1},
            )
            assert response.status_code == 503
            payload = response.json()["error"]
            assert payload["code"] == "SERVICE_BUSY"
    finally:
        lease.release()
        reset_bulkheads()


@pytest.mark.asyncio
async def test_ops_slo_shape() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t1", role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/v1/health")
        response = await client.get("/v1/ops/slo", headers=headers)
        assert response.status_code in {200, 503}
        if response.status_code == 200:
            payload = response.json()["data"]
            assert "availability" in payload
            assert "p95" in payload
            assert "error_budget" in payload
            assert "status" in payload


@pytest.mark.asyncio
async def test_admin_maintenance_task_validation() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t1", role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/admin/maintenance/run?task=unknown", headers=headers)
        assert response.status_code == 422
        response = await client.post("/v1/admin/maintenance/run?task=prune_idempotency", headers=headers)
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["task"] == "prune_idempotency"
        response = await client.post("/v1/admin/maintenance/run?task=prune_retention_all", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["task"] == "prune_retention_all"
        status = await client.get("/v1/admin/retention/status", headers=headers)
        assert status.status_code == 200
        status_payload = status.json()["data"]
        assert status_payload["next_schedule"] == "manual"
        assert "prune_retention_all" in status_payload["last_run_by_task"]
