from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, select

from nexusrag.apps.api import rate_limit
from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    ApiKey,
    AuditEvent,
    Document,
    DocumentLabel,
    DocumentPermission,
    PlanUpgradeRequest,
    TenantFeatureOverride,
    TenantPlanAssignment,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.auth.api_keys import generate_api_key
from nexusrag.services.entitlements import reset_entitlements_cache
from nexusrag.tests.utils.auth import create_test_api_key


def _apply_env(monkeypatch, **overrides: str) -> None:
    # Apply environment overrides and reset cached settings.
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
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
        await session.execute(delete(PlanUpgradeRequest).where(PlanUpgradeRequest.tenant_id == tenant_id))
        await session.execute(delete(TenantFeatureOverride).where(TenantFeatureOverride.tenant_id == tenant_id))
        await session.execute(delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.execute(delete(DocumentPermission).where(DocumentPermission.tenant_id == tenant_id))
        await session.execute(delete(DocumentLabel).where(DocumentLabel.tenant_id == tenant_id))
        await session.execute(delete(Document).where(Document.tenant_id == tenant_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_admin_can_create_list_and_revoke_keys(monkeypatch) -> None:
    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_payload = {"name": "ci-bot", "role": "editor"}
        response = await client.post("/self-serve/api-keys", json=create_payload, headers=headers)
        assert response.status_code == 200
        created = response.json()
        assert created["api_key"].startswith("nrgk_")
        assert created["role"] == "editor"

        response = await client.get("/self-serve/api-keys", headers=headers)
        assert response.status_code == 200
        items = response.json()["items"]
        assert all("api_key" not in item for item in items)
        created_ids = {item["key_id"] for item in items}
        assert created["key_id"] in created_ids

        response = await client.post(f"/self-serve/api-keys/{created['key_id']}/revoke", headers=headers)
        assert response.status_code == 200
        revoked = response.json()
        assert revoked["revoked_at"] is not None

        response = await client.post(f"/self-serve/api-keys/{created['key_id']}/revoke", headers=headers)
        assert response.status_code == 200
        assert response.json()["revoked_at"] == revoked["revoked_at"]

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_non_admin_forbidden(monkeypatch) -> None:
    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/self-serve/api-keys", headers=headers)
        assert response.status_code == 403
        response = await client.get("/self-serve/plan", headers=headers)
        assert response.status_code == 403

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_key_limit_enforced(monkeypatch) -> None:
    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch, SELF_SERVE_MAX_ACTIVE_KEYS=1)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/self-serve/api-keys",
            json={"name": "extra", "role": "reader"},
            headers=headers,
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "KEY_LIMIT_REACHED"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_usage_summary_and_plan(monkeypatch) -> None:
    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200

        response = await client.get("/self-serve/usage/summary", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["window_days"] == 30
        assert "requests" in payload
        assert set(payload["requests"]["by_route_class"].keys()) == {
            "run",
            "read",
            "mutation",
            "ops",
        }

        response = await client.get("/self-serve/plan", headers=headers)
        assert response.status_code == 200
        assert response.json()["plan_id"] == "enterprise"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_upgrade_request_persists_and_audits(monkeypatch) -> None:
    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="free",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/self-serve/plan/upgrade-request",
            json={"target_plan": "pro", "reason": "Need more features"},
            headers=headers,
        )
        assert response.status_code == 202
        request_id = response.json()["request_id"]

    async with SessionLocal() as session:
        upgrade = await session.get(PlanUpgradeRequest, request_id)
        assert upgrade is not None
        result = await session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.event_type == "plan.upgrade_requested",
            )
        )
        events = list(result.scalars().all())
        assert events

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_billing_webhook_test_gated_and_configured(monkeypatch) -> None:
    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, free_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="free",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/self-serve/billing/webhook-test", headers=free_headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_NOT_ENABLED"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_expired_key_is_rejected_and_audited(monkeypatch) -> None:
    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch)
    expired_at = datetime.now(timezone.utc) - timedelta(days=1)
    _raw_key, headers, _user_id, key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
        key_expires_at=expired_at,
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/self-serve/plan", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_EXPIRED_KEY"

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.actor_id == key_id,
                    AuditEvent.event_type == "auth.api_key.expired",
                )
            )
        ).scalars().all()
        assert rows

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_inactive_report_returns_stale_and_expired_keys(monkeypatch) -> None:
    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    old_now = datetime.now(timezone.utc) - timedelta(days=120)

    async with SessionLocal() as session:
        stale_user = User(id=uuid4().hex, tenant_id=tenant_id, email=None, role="reader", is_active=True)
        stale_key_id, _raw_stale, stale_prefix, stale_hash = generate_api_key()
        stale_key = ApiKey(
            id=stale_key_id,
            user_id=stale_user.id,
            tenant_id=tenant_id,
            key_prefix=stale_prefix,
            key_hash=stale_hash,
            name="stale",
            last_used_at=old_now,
        )
        expired_user = User(id=uuid4().hex, tenant_id=tenant_id, email=None, role="reader", is_active=True)
        expired_key_id, _raw_expired, expired_prefix, expired_hash = generate_api_key()
        expired_key = ApiKey(
            id=expired_key_id,
            user_id=expired_user.id,
            tenant_id=tenant_id,
            key_prefix=expired_prefix,
            key_hash=expired_hash,
            name="expired",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        session.add_all([stale_user, expired_user])
        # Flush user rows before API keys to satisfy FK ordering deterministically.
        await session.flush()
        session.add_all([stale_key, expired_key])
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/self-serve/api-keys/inactive-report?inactive_days=30", headers=headers)
        assert response.status_code == 200
        body = response.json()
        payload = body["data"] if "data" in body else body
        ids = {item["key_id"] for item in payload["items"]}
        assert stale_key_id in ids
        assert expired_key_id in ids

    await _cleanup_tenant(tenant_id)

    tenant_id = f"t-selfserve-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, ent_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/self-serve/billing/webhook-test", headers=ent_headers)
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "BILLING_WEBHOOK_NOT_CONFIGURED"

    class StubClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, _url, content, headers):
            return Response(200, content=content, headers=headers)

    monkeypatch.setenv("BILLING_WEBHOOK_ENABLED", "true")
    monkeypatch.setenv("BILLING_WEBHOOK_URL", "http://billing.test")
    monkeypatch.setenv("BILLING_WEBHOOK_SECRET", "secret")
    get_settings.cache_clear()
    reset_entitlements_cache()

    from nexusrag.services import billing_webhook

    monkeypatch.setattr(billing_webhook.httpx, "AsyncClient", StubClient)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/self-serve/billing/webhook-test", headers=ent_headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["sent"] is True
        assert payload["status_code"] == 200

    await _cleanup_tenant(tenant_id)
