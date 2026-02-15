from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.domain.models import (
    ApiKey,
    AuthorizationPolicy,
    Corpus,
    Document,
    DocumentLabel,
    DocumentPermission,
    TenantPlanAssignment,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key
from nexusrag.tests.utils.authz import grant_document_permission


def _utc_now() -> datetime:
    # Use UTC timestamps for deterministic authz tests.
    return datetime.now(timezone.utc)


async def _seed_corpus(*, tenant_id: str, corpus_id: str) -> None:
    # Insert a corpus row for run and document tests.
    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Authz Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector"}},
            )
        )
        await session.commit()


async def _seed_document(*, tenant_id: str, corpus_id: str, document_id: str) -> None:
    # Insert a document row without ingestion for authz tests.
    async with SessionLocal() as session:
        session.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                corpus_id=corpus_id,
                filename="authz.txt",
                content_type="text/plain",
                source="raw_text",
                ingest_source="raw_text",
                status="succeeded",
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )
        await session.commit()


async def _seed_policy(
    *,
    tenant_id: str,
    name: str,
    effect: str,
    resource_type: str,
    action: str,
    condition_json: dict,
    priority: int,
) -> None:
    # Insert an authorization policy row for authz integration tests.
    async with SessionLocal() as session:
        session.add(
            AuthorizationPolicy(
                id=uuid4().hex,
                tenant_id=tenant_id,
                name=name,
                version=1,
                effect=effect,
                resource_type=resource_type,
                action=action,
                condition_json=condition_json,
                priority=priority,
                enabled=True,
                created_by="test-suite",
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )
        await session.commit()


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped rows to keep authz tests isolated.
    async with SessionLocal() as session:
        await session.execute(delete(DocumentPermission).where(DocumentPermission.tenant_id == tenant_id))
        await session.execute(delete(DocumentLabel).where(DocumentLabel.tenant_id == tenant_id))
        await session.execute(delete(Document).where(Document.tenant_id == tenant_id))
        await session.execute(delete(Corpus).where(Corpus.tenant_id == tenant_id))
        await session.execute(delete(AuthorizationPolicy).where(AuthorizationPolicy.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.execute(delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_document_read_denied_without_acl_and_policy() -> None:
    tenant_id = f"t-authz-deny-{uuid4().hex}"
    corpus_id = f"c-authz-{uuid4().hex}"
    document_id = f"doc-authz-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        seed_authz_policies=False,
    )
    await _seed_corpus(tenant_id=tenant_id, corpus_id=corpus_id)
    await _seed_document(tenant_id=tenant_id, corpus_id=corpus_id, document_id=document_id)

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/v1/documents/{document_id}", headers=headers)
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "AUTHZ_DENIED"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_document_permission_grant_allows_read() -> None:
    tenant_id = f"t-authz-allow-{uuid4().hex}"
    corpus_id = f"c-authz-{uuid4().hex}"
    document_id = f"doc-authz-{uuid4().hex}"
    _raw_key, reader_headers, user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    _raw_key, admin_headers, _admin_id, _admin_key = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
    )
    await _seed_corpus(tenant_id=tenant_id, corpus_id=corpus_id)
    await _seed_document(tenant_id=tenant_id, corpus_id=corpus_id, document_id=document_id)

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            grant_resp = await client.post(
                f"/v1/admin/authz/documents/{document_id}/permissions",
                headers=admin_headers,
                json={
                    "principal_type": "user",
                    "principal_id": user_id,
                    "permission": "read",
                },
            )
            assert grant_resp.status_code == 201

            response = await client.get(f"/v1/documents/{document_id}", headers=reader_headers)
            assert response.status_code == 200
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_policy_deny_overrides_allow() -> None:
    tenant_id = f"t-authz-deny-policy-{uuid4().hex}"
    corpus_id = f"c-authz-{uuid4().hex}"
    document_id = f"doc-authz-{uuid4().hex}"
    _raw_key, reader_headers, user_id, key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    await _seed_corpus(tenant_id=tenant_id, corpus_id=corpus_id)
    await _seed_document(tenant_id=tenant_id, corpus_id=corpus_id, document_id=document_id)

    async with SessionLocal() as session:
        session.add(
            DocumentLabel(
                id=uuid4().hex,
                tenant_id=tenant_id,
                document_id=document_id,
                key="sensitivity",
                value="high",
            )
        )
        await grant_document_permission(
            session=session,
            tenant_id=tenant_id,
            document_id=document_id,
            principal_type="user",
            principal_id=user_id,
            permission="read",
            granted_by=key_id,
        )
        await session.commit()

    await _seed_policy(
        tenant_id=tenant_id,
        name="deny-high-sensitivity",
        effect="deny",
        resource_type="document",
        action="read",
        condition_json={"eq": [{"var": "resource.labels.sensitivity"}, "high"]},
        priority=200,
    )

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/v1/documents/{document_id}", headers=reader_headers)
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "AUTHZ_DENIED"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_ui_list_filters_unauthorized_documents() -> None:
    tenant_id = f"t-authz-ui-{uuid4().hex}"
    corpus_id = f"c-authz-ui-{uuid4().hex}"
    _raw_key, headers, user_id, key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    now = _utc_now()
    doc_denied = Document(
        id=f"doc-{uuid4().hex}",
        tenant_id=tenant_id,
        corpus_id=corpus_id,
        filename="denied.txt",
        content_type="text/plain",
        source="raw_text",
        ingest_source="raw_text",
        status="succeeded",
        created_at=now,
        updated_at=now,
    )
    doc_allowed = Document(
        id=f"doc-{uuid4().hex}",
        tenant_id=tenant_id,
        corpus_id=corpus_id,
        filename="allowed.txt",
        content_type="text/plain",
        source="raw_text",
        ingest_source="raw_text",
        status="succeeded",
        created_at=now - timedelta(minutes=1),
        updated_at=now - timedelta(minutes=1),
    )

    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Authz UI",
                provider_config_json={"retrieval": {"provider": "local_pgvector"}},
            )
        )
        session.add_all([doc_denied, doc_allowed])
        await grant_document_permission(
            session=session,
            tenant_id=tenant_id,
            document_id=doc_allowed.id,
            principal_type="user",
            principal_id=user_id,
            permission="read",
            granted_by=key_id,
        )
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/ui/documents?limit=1", headers=headers)
            assert response.status_code == 200
            data = response.json()["data"]
            assert len(data["items"]) == 1
            assert data["items"][0]["id"] == doc_allowed.id
            assert data["page"]["has_more"] is False
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_authz_admin_endpoints_require_admin() -> None:
    tenant_id = f"t-authz-admin-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="editor",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/admin/authz/policies", headers=headers)
            assert response.status_code == 403
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_run_preflight_denies_corpus_policy() -> None:
    tenant_id = f"t-authz-run-{uuid4().hex}"
    corpus_id = f"c-authz-run-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    await _seed_corpus(tenant_id=tenant_id, corpus_id=corpus_id)
    await _seed_policy(
        tenant_id=tenant_id,
        name="deny-run",
        effect="deny",
        resource_type="corpus",
        action="run",
        condition_json={},
        priority=200,
    )

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/run",
                headers=headers,
                json={
                    "session_id": f"sess-{uuid4().hex}",
                    "corpus_id": corpus_id,
                    "message": "hello",
                    "top_k": 3,
                    "audio": False,
                },
            )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "AUTHZ_DENIED"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_authz_admin_tenant_isolation() -> None:
    tenant_id = f"t-authz-a-{uuid4().hex}"
    other_tenant = f"t-authz-b-{uuid4().hex}"
    corpus_id = f"c-authz-{uuid4().hex}"
    document_id = f"doc-authz-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=other_tenant,
        role="admin",
    )
    await _seed_corpus(tenant_id=tenant_id, corpus_id=corpus_id)
    await _seed_document(tenant_id=tenant_id, corpus_id=corpus_id, document_id=document_id)

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/v1/admin/authz/documents/{document_id}/permissions",
                headers=headers,
            )
            assert response.status_code == 404
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_tenant(other_tenant)
