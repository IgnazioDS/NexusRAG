from __future__ import annotations

import argparse
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from nexusrag.apps.api.main import create_app
from nexusrag.domain.models import AuditEvent, ApiKey, User
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.audit import record_event
from nexusrag.tests.utils.auth import create_test_api_key
from scripts import create_api_key as create_api_key_script
from scripts import revoke_api_key as revoke_api_key_script


def _tenant_id() -> str:
    # Use unique tenant ids to keep audit tests isolated.
    return f"t-audit-{uuid4().hex}"


async def _count_events(*, event_type: str | None = None, outcome: str | None = None) -> int:
    # Count matching audit events to validate event emission deltas.
    async with SessionLocal() as session:
        stmt = select(func.count()).select_from(AuditEvent)
        if event_type:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        if outcome:
            stmt = stmt.where(AuditEvent.outcome == outcome)
        result = await session.execute(stmt)
        return int(result.scalar() or 0)


async def _fetch_events(
    *,
    tenant_id: str,
    event_type: str | None = None,
    outcome: str | None = None,
) -> list[AuditEvent]:
    # Fetch audit events for assertions without using the API.
    async with SessionLocal() as session:
        stmt = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
        if event_type:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        if outcome:
            stmt = stmt.where(AuditEvent.outcome == outcome)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped audit and auth rows to keep tests isolated.
    async with SessionLocal() as session:
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_unauthorized_request_emits_auth_failure_event() -> None:
    app = create_app()
    before = await _count_events(event_type="auth.access.failure", outcome="failure")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents")
    assert response.status_code == 401

    after = await _count_events(event_type="auth.access.failure", outcome="failure")
    assert after == before + 1


@pytest.mark.asyncio
async def test_authorized_request_emits_auth_success_and_ops_event() -> None:
    tenant_id = _tenant_id()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
    )
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/health", headers=headers)
    assert response.status_code == 200

    auth_events = await _fetch_events(tenant_id=tenant_id, event_type="auth.access.success")
    ops_events = await _fetch_events(tenant_id=tenant_id, event_type="ops.viewed")
    assert auth_events
    assert any(event.resource_id == "health" for event in ops_events)

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_reader_accessing_audit_endpoint_emits_rbac_forbidden() -> None:
    tenant_id = _tenant_id()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit/events", headers=headers)
    assert response.status_code == 403

    rbac_events = await _fetch_events(
        tenant_id=tenant_id,
        event_type="rbac.forbidden",
        outcome="failure",
    )
    assert rbac_events

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_audit_events_endpoint_scoped_paginated_and_filtered() -> None:
    tenant_id = _tenant_id()
    other_tenant = _tenant_id()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
    )

    async with SessionLocal() as session:
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id="test",
            actor_role=None,
            event_type="documents.deleted",
            outcome="success",
            resource_type="document",
            resource_id="doc-a",
            metadata={"corpus_id": "c-a"},
            commit=True,
        )
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id="test",
            actor_role=None,
            event_type="documents.deleted",
            outcome="success",
            resource_type="document",
            resource_id="doc-b",
            metadata={"corpus_id": "c-a"},
            commit=True,
        )
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id="test",
            actor_role=None,
            event_type="run.invoked",
            outcome="success",
            resource_type="run",
            resource_id="run-a",
            metadata={"session_id": "s-a"},
            commit=True,
        )
        await record_event(
            session=session,
            tenant_id=other_tenant,
            actor_type="system",
            actor_id="test",
            actor_role=None,
            event_type="documents.deleted",
            outcome="success",
            resource_type="document",
            resource_id="doc-x",
            metadata={"corpus_id": "c-x"},
            commit=True,
        )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/audit/events?limit=2", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["items"]) == 2
        assert payload["next_offset"] == 2
        assert all(item["tenant_id"] == tenant_id for item in payload["items"])

        response = await client.get("/audit/events?limit=2&offset=2", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"]
        assert all(item["tenant_id"] == tenant_id for item in payload["items"])

        response = await client.get(
            "/audit/events?event_type=documents.deleted&limit=5",
            headers=headers,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"]
        assert all(item["event_type"] == "documents.deleted" for item in payload["items"])

        response = await client.get(
            f"/audit/events?tenant_id={other_tenant}",
            headers=headers,
        )
        assert response.status_code == 403

    await _cleanup_tenant(tenant_id)
    await _cleanup_tenant(other_tenant)


@pytest.mark.asyncio
async def test_audit_event_metadata_redaction() -> None:
    tenant_id = _tenant_id()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
    )
    resource_id = f"redact-{uuid4().hex}"

    async with SessionLocal() as session:
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id="test",
            actor_role=None,
            event_type="system.error",
            outcome="failure",
            resource_type="system",
            resource_id=resource_id,
            metadata={
                "api_key": "secret",
                "authorization": "Bearer abc",
                "nested": {"token": "xyz", "safe": "ok"},
                "safe": "ok",
            },
            commit=True,
        )
        result = await session.execute(
            select(AuditEvent).where(AuditEvent.resource_id == resource_id)
        )
        event = result.scalar_one()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/audit/events/{event.id}", headers=headers)
        assert response.status_code == 200
        payload = response.json()

    metadata = payload["metadata_json"]
    assert metadata["api_key"] == "[REDACTED]"
    assert metadata["authorization"] == "[REDACTED]"
    assert metadata["nested"]["token"] == "[REDACTED]"
    assert metadata["nested"]["safe"] == "ok"
    assert metadata["safe"] == "ok"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_key_scripts_emit_audit_events() -> None:
    tenant_id = _tenant_id()
    key_name = f"script-key-{uuid4().hex}"

    args = argparse.Namespace(
        tenant=tenant_id,
        role="admin",
        name=key_name,
        user_id=None,
        email=None,
    )
    result = await create_api_key_script._create_key(args)
    assert result == 0

    async with SessionLocal() as session:
        row = await session.execute(select(ApiKey).where(ApiKey.name == key_name))
        api_key = row.scalar_one()

    result = await revoke_api_key_script._revoke_key(api_key.id)
    assert result == 0

    created_events = await _fetch_events(tenant_id=tenant_id, event_type="auth.api_key.created")
    revoked_events = await _fetch_events(tenant_id=tenant_id, event_type="auth.api_key.revoked")
    assert created_events
    assert revoked_events

    await _cleanup_tenant(tenant_id)
