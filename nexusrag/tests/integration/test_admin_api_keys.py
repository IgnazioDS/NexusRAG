from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api.main import create_app
from nexusrag.domain.models import ApiKey, AuditEvent, User
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.auth.api_keys import generate_api_key
from nexusrag.tests.utils.auth import create_test_api_key


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant test rows to keep lifecycle tests deterministic across runs.
    async with SessionLocal() as session:
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_admin_api_keys_list_supports_inactive_filter() -> None:
    tenant_id = f"t-admin-keys-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")
    old_now = datetime.now(timezone.utc) - timedelta(days=200)
    async with SessionLocal() as session:
        stale_user = User(id=uuid4().hex, tenant_id=tenant_id, email=None, role="reader", is_active=True)
        stale_key_id, _raw, stale_prefix, stale_hash = generate_api_key()
        stale_key = ApiKey(
            id=stale_key_id,
            user_id=stale_user.id,
            tenant_id=tenant_id,
            key_prefix=stale_prefix,
            key_hash=stale_hash,
            name="stale-key",
            last_used_at=old_now,
        )
        session.add(stale_user)
        await session.flush()
        session.add(stale_key)
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get(f"/v1/admin/api-keys?tenant_id={tenant_id}", headers=headers)
        assert listed.status_code == 200
        payload = listed.json()["data"]
        assert payload["tenant_id"] == tenant_id
        assert any(row["key_id"] == stale_key_id for row in payload["items"])

        inactive_only = await client.get(
            f"/v1/admin/api-keys?tenant_id={tenant_id}&inactive_days=30&include_only_inactive=true",
            headers=headers,
        )
        assert inactive_only.status_code == 200
        filtered = inactive_only.json()["data"]["items"]
        filtered_ids = {row["key_id"] for row in filtered}
        assert stale_key_id in filtered_ids

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_admin_api_keys_patch_updates_lifecycle_and_audits() -> None:
    tenant_id = f"t-admin-keys-{uuid4().hex}"
    _raw_key, headers, _user_id, key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")
    app = create_app()
    transport = ASGITransport(app=app)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        deactivate = await client.patch(
            f"/v1/admin/api-keys/{key_id}",
            headers=headers,
            json={"active": False, "expires_at": expires_at.isoformat()},
        )
        assert deactivate.status_code == 200
        assert deactivate.json()["data"]["revoked_at"] is not None

        reactivate = await client.patch(
            f"/v1/admin/api-keys/{key_id}",
            headers=headers,
            json={"active": True},
        )
        assert reactivate.status_code == 200
        assert reactivate.json()["data"]["revoked_at"] is None

        revoke = await client.patch(
            f"/v1/admin/api-keys/{key_id}",
            headers=headers,
            json={"revoke": True},
        )
        assert revoke.status_code == 200
        assert revoke.json()["data"]["revoked_at"] is not None

    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditEvent.event_type)
                .where(AuditEvent.tenant_id == tenant_id)
                .where(AuditEvent.resource_id == key_id)
            )
        ).scalars().all()
        assert "auth.api_key.deactivated" in events
        assert "auth.api_key.reactivated" in events
        assert "auth.api_key.revoked" in events

    await _cleanup_tenant(tenant_id)
