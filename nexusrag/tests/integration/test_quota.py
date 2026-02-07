from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api import rate_limit
from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import AuditEvent, PlanLimit, QuotaSoftCapEvent, UsageCounter
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.quota import parse_period_start, reset_quota_service
from nexusrag.tests.utils.auth import create_test_api_key


def _tenant_id() -> str:
    # Generate unique tenant ids for quota integration tests.
    return f"t-quota-{uuid4().hex}"


def _apply_env(monkeypatch, **overrides: str) -> None:
    # Apply environment overrides and reset cached settings/limiters.
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()
    reset_quota_service()


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    # Clear settings caches between tests to avoid env leakage.
    yield
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()
    reset_quota_service()


async def _seed_plan_limit(tenant_id: str, **kwargs: object) -> None:
    # Insert tenant quota limits for integration tests.
    async with SessionLocal() as session:
        session.add(PlanLimit(tenant_id=tenant_id, **kwargs))
        await session.commit()


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove quota-related rows to keep tests isolated.
    async with SessionLocal() as session:
        await session.execute(delete(UsageCounter).where(UsageCounter.tenant_id == tenant_id))
        await session.execute(delete(QuotaSoftCapEvent).where(QuotaSoftCapEvent.tenant_id == tenant_id))
        await session.execute(delete(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_quota_within_limits_adds_headers(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _apply_env(
        monkeypatch,
        RL_KEY_READ_RPS=100,
        RL_KEY_READ_BURST=100,
        RL_TENANT_READ_RPS=100,
        RL_TENANT_READ_BURST=100,
    )
    await _seed_plan_limit(
        tenant_id,
        daily_requests_limit=10,
        monthly_requests_limit=20,
        soft_cap_ratio=0.8,
        hard_cap_enabled=True,
    )

    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("X-Quota-Day-Limit") == "10"
    assert response.headers.get("X-Quota-Day-Used") == "1"
    assert response.headers.get("X-Quota-Day-Remaining") == "9"
    assert response.headers.get("X-Quota-Month-Limit") == "20"
    assert response.headers.get("X-Quota-Month-Used") == "1"
    assert response.headers.get("X-Quota-Month-Remaining") == "19"
    assert response.headers.get("X-Quota-SoftCap-Reached") == "false"
    assert response.headers.get("X-Quota-HardCap-Mode") == "enforce"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_soft_cap_event_emitted_once(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _apply_env(
        monkeypatch,
        RL_KEY_READ_RPS=100,
        RL_KEY_READ_BURST=100,
        RL_TENANT_READ_RPS=100,
        RL_TENANT_READ_BURST=100,
    )
    await _seed_plan_limit(
        tenant_id,
        daily_requests_limit=4,
        monthly_requests_limit=10,
        soft_cap_ratio=0.5,
        hard_cap_enabled=True,
    )

    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200

    async with SessionLocal() as session:
        result = await session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.event_type == "quota.soft_cap_reached",
            )
        )
        events = list(result.scalars().all())
        assert len(events) == 1

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_hard_cap_enforced_blocks(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _apply_env(
        monkeypatch,
        RL_KEY_READ_RPS=100,
        RL_KEY_READ_BURST=100,
        RL_TENANT_READ_RPS=100,
        RL_TENANT_READ_BURST=100,
    )
    await _seed_plan_limit(
        tenant_id,
        daily_requests_limit=1,
        monthly_requests_limit=100,
        soft_cap_ratio=0.8,
        hard_cap_enabled=True,
    )

    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers)

    assert response.status_code == 402
    detail = response.json()["detail"]
    assert detail["code"] == "QUOTA_EXCEEDED"
    assert detail["period"] == "day"
    assert response.headers.get("X-Quota-HardCap-Mode") == "enforce"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_hard_cap_observe_allows_and_emits_overage(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _apply_env(
        monkeypatch,
        RL_KEY_READ_RPS=100,
        RL_KEY_READ_BURST=100,
        RL_TENANT_READ_RPS=100,
        RL_TENANT_READ_BURST=100,
    )
    await _seed_plan_limit(
        tenant_id,
        daily_requests_limit=1,
        monthly_requests_limit=100,
        soft_cap_ratio=0.8,
        hard_cap_enabled=False,
    )

    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200
        assert response.headers.get("X-Quota-HardCap-Mode") == "observe"

    async with SessionLocal() as session:
        result = await session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.event_type == "quota.overage_observed",
            )
        )
        assert result.scalars().first() is not None

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_rate_limited_requests_do_not_increment_quota(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _apply_env(
        monkeypatch,
        RL_KEY_READ_RPS=0,
        RL_KEY_READ_BURST=1,
        RL_TENANT_READ_RPS=0,
        RL_TENANT_READ_BURST=1,
    )
    await _seed_plan_limit(
        tenant_id,
        daily_requests_limit=100,
        monthly_requests_limit=200,
        soft_cap_ratio=0.8,
        hard_cap_enabled=True,
    )

    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 429

    period_start = parse_period_start("day", datetime.now(timezone.utc).date())
    async with SessionLocal() as session:
        result = await session.execute(
            select(UsageCounter).where(
                UsageCounter.tenant_id == tenant_id,
                UsageCounter.period_type == "day",
                UsageCounter.period_start == period_start,
            )
        )
        counter = result.scalar_one_or_none()
        assert counter is not None
        assert counter.requests_count == 1

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_admin_quota_endpoints_authz(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _apply_env(monkeypatch, RL_KEY_READ_RPS=100, RL_TENANT_READ_RPS=100)

    _raw_key, reader_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    _raw_key, admin_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/admin/quotas/{tenant_id}", headers=reader_headers)
        assert response.status_code == 403

        response = await client.get(f"/admin/quotas/{tenant_id}", headers=admin_headers)
        assert response.status_code == 200

        response = await client.patch(
            f"/admin/quotas/{tenant_id}",
            headers=admin_headers,
            json={"daily_requests_limit": 10},
        )
        assert response.status_code == 200

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_webhook_failure_is_non_blocking(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _apply_env(
        monkeypatch,
        RL_KEY_READ_RPS=100,
        RL_KEY_READ_BURST=100,
        RL_TENANT_READ_RPS=100,
        RL_TENANT_READ_BURST=100,
        BILLING_WEBHOOK_ENABLED=True,
        BILLING_WEBHOOK_URL="http://localhost:9999/hooks",
        BILLING_WEBHOOK_SECRET="secret",
        BILLING_WEBHOOK_TIMEOUT_MS=100,
    )
    await _seed_plan_limit(
        tenant_id,
        daily_requests_limit=2,
        monthly_requests_limit=10,
        soft_cap_ratio=0.5,
        hard_cap_enabled=True,
    )

    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200

    async with SessionLocal() as session:
        result = await session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.event_type == "billing.webhook.failure",
            )
        )
        assert result.scalars().first() is not None

    await _cleanup_tenant(tenant_id)
