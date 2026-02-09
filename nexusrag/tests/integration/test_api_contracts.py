from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api import rate_limit
from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import ApiKey, IdempotencyRecord, PlanLimit, UsageCounter, User
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.entitlements import reset_entitlements_cache
from nexusrag.tests.utils.auth import create_test_api_key


def _apply_env(monkeypatch, **overrides: str) -> None:
    # Apply environment overrides and reset cached settings.
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()
    reset_entitlements_cache()


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    # Ensure settings/entitlements caches are reset between tests.
    yield
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()
    reset_entitlements_cache()


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped rows to keep tests isolated.
    async with SessionLocal() as session:
        await session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.tenant_id == tenant_id))
        await session.execute(delete(UsageCounter).where(UsageCounter.tenant_id == tenant_id))
        await session.execute(delete(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_v1_success_envelope_health(monkeypatch) -> None:
    _apply_env(monkeypatch)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["data"]["status"] == "ok"
        assert payload["meta"]["api_version"] == "v1"
        assert payload["meta"]["request_id"]


@pytest.mark.asyncio
async def test_v1_error_envelope_unauthorized(monkeypatch) -> None:
    _apply_env(monkeypatch)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/documents")
        assert response.status_code == 401
        payload = response.json()
        assert payload["error"]["code"] == "AUTH_UNAUTHORIZED"
        assert payload["meta"]["api_version"] == "v1"


@pytest.mark.asyncio
async def test_v1_error_envelope_feature_not_enabled(monkeypatch) -> None:
    tenant_id = f"t-contract-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="free",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/ops/health", headers=headers)
        assert response.status_code == 403
        payload = response.json()
        assert payload["error"]["code"] == "FEATURE_NOT_ENABLED"
        assert payload["meta"]["api_version"] == "v1"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_v1_rate_limited_error_envelope(monkeypatch) -> None:
    tenant_id = f"t-contract-{uuid4().hex}"
    _apply_env(
        monkeypatch,
        RL_KEY_READ_RPS=0,
        RL_KEY_READ_BURST=1,
        RL_TENANT_READ_RPS=0,
        RL_TENANT_READ_BURST=1,
    )
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/v1/documents", headers=headers)
        assert first.status_code == 200
        second = await client.get("/v1/documents", headers=headers)
        assert second.status_code == 429
        payload = second.json()
        assert payload["error"]["code"] == "RATE_LIMITED"
        assert payload["meta"]["api_version"] == "v1"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_v1_quota_exceeded_error_envelope(monkeypatch) -> None:
    tenant_id = f"t-contract-{uuid4().hex}"
    _apply_env(
        monkeypatch,
        RL_KEY_READ_RPS=100,
        RL_KEY_READ_BURST=200,
        RL_TENANT_READ_RPS=100,
        RL_TENANT_READ_BURST=200,
    )
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    async with SessionLocal() as session:
        plan_limit = PlanLimit(
            tenant_id=tenant_id,
            daily_requests_limit=1,
            monthly_requests_limit=100,
            soft_cap_ratio=0.8,
            hard_cap_enabled=True,
        )
        session.add(plan_limit)
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/v1/documents", headers=headers)
        assert first.status_code == 200
        second = await client.get("/v1/documents", headers=headers)
        assert second.status_code == 402
        payload = second.json()
        assert payload["error"]["code"] == "QUOTA_EXCEEDED"
        assert payload["meta"]["api_version"] == "v1"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_v1_idempotency_replay_and_conflict(monkeypatch) -> None:
    tenant_id = f"t-contract-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    idem_headers = {**headers, "Idempotency-Key": "idem-key-1"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"name": "ci-bot", "role": "reader"}
        first = await client.post("/v1/self-serve/api-keys", json=payload, headers=idem_headers)
        assert first.status_code == 200
        body_first = first.json()

        replay = await client.post("/v1/self-serve/api-keys", json=payload, headers=idem_headers)
        assert replay.status_code == 200
        assert replay.headers.get("Idempotency-Replayed") == "true"
        body_replay = replay.json()
        assert body_replay == body_first

        conflict_payload = {"name": "ci-bot", "role": "editor"}
        conflict = await client.post(
            "/v1/self-serve/api-keys",
            json=conflict_payload,
            headers=idem_headers,
        )
        assert conflict.status_code == 409
        conflict_body = conflict.json()
        assert conflict_body["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_legacy_routes_include_deprecation_headers(monkeypatch) -> None:
    _apply_env(monkeypatch)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("Deprecation") == "true"
        assert "Sunset" in response.headers
        assert "Link" in response.headers
        assert "data" not in response.json()


@pytest.mark.asyncio
async def test_openapi_contains_v1_and_security(monkeypatch) -> None:
    _apply_env(monkeypatch)
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "/v1/health" in schema.get("paths", {})
        security = schema.get("components", {}).get("securitySchemes", {})
        assert "BearerAuth" in security
        documents = schema["paths"].get("/v1/documents", {})
        get_op = documents.get("get", {})
        assert get_op.get("security")
