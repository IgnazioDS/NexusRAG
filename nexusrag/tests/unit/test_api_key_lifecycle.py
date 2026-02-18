from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from nexusrag.domain.models import ApiKey, AuditEvent, User
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.auth.api_keys import generate_api_key
from scripts.rotate_api_key import _rotate


@pytest.mark.asyncio
async def test_rotate_api_key_script_emits_audit_event() -> None:
    tenant_id = f"t-rotate-{uuid4().hex}"
    user_id = uuid4().hex
    old_key_id, _raw_old, old_prefix, old_hash = generate_api_key()
    async with SessionLocal() as session:
        session.add(User(id=user_id, tenant_id=tenant_id, email=None, role="admin", is_active=True))
        await session.flush()
        session.add(
            ApiKey(
                id=old_key_id,
                user_id=user_id,
                tenant_id=tenant_id,
                key_prefix=old_prefix,
                key_hash=old_hash,
                name="to-rotate",
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        await session.commit()

    args = argparse.Namespace(old_key_id=old_key_id, name="rotated", keep_old_active=False)
    status = await _rotate(args)
    assert status == 0

    async with SessionLocal() as session:
        keys = (
            await session.execute(select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at.asc()))
        ).scalars().all()
        assert len(keys) == 2
        assert keys[0].id == old_key_id
        assert keys[0].revoked_at is not None
        rotated_events = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.event_type == "auth.api_key.rotated",
                )
            )
        ).scalars().all()
        assert rotated_events

        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()
