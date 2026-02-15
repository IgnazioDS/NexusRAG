from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    ApiKey,
    AuditEvent,
    Chunk,
    Corpus,
    Document,
    DocumentLabel,
    DocumentPermission,
    TenantPlanAssignment,
    UiAction,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.ingest.ingestion import write_text_to_storage
from nexusrag.tests.utils.auth import create_test_api_key
from nexusrag.tests.utils.authz import grant_document_permission, grant_document_permissions


def _utc_now() -> datetime:
    # Use UTC timestamps for deterministic ordering in UI tests.
    return datetime.now(timezone.utc)


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped rows to keep integration tests isolated.
    async with SessionLocal() as session:
        # Delete chunks via tenant corpora to satisfy FK constraints.
        corpus_ids = select(Corpus.id).where(Corpus.tenant_id == tenant_id)
        await session.execute(delete(Chunk).where(Chunk.corpus_id.in_(corpus_ids)))
        await session.execute(delete(UiAction).where(UiAction.tenant_id == tenant_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.execute(delete(DocumentPermission).where(DocumentPermission.tenant_id == tenant_id))
        await session.execute(delete(DocumentLabel).where(DocumentLabel.tenant_id == tenant_id))
        await session.execute(delete(Document).where(Document.tenant_id == tenant_id))
        await session.execute(delete(Corpus).where(Corpus.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.execute(
            delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_ui_bootstrap_admin_and_editor() -> None:
    tenant_id = f"t-ui-{uuid4().hex}"
    _raw_key, admin_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
    )
    _raw_key, editor_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="editor",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/ui/bootstrap", headers=admin_headers)
            assert response.status_code == 200
            payload = response.json()["data"]
            assert payload["principal"]["tenant_id"] == tenant_id
            assert payload["principal"]["role"] == "admin"
            assert payload["api"]["version"] == "v1"

            response = await client.get("/v1/ui/bootstrap", headers=editor_headers)
            assert response.status_code == 200
            payload = response.json()["data"]
            assert payload["principal"]["tenant_id"] == tenant_id
            assert payload["principal"]["role"] == "editor"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_ui_documents_pagination_and_invalid_cursor() -> None:
    tenant_id = f"t-ui-{uuid4().hex}"
    _raw_key, headers, user_id, key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    corpus_id = f"c-ui-{uuid4().hex}"
    now = _utc_now()
    docs = [
        Document(
            id=f"doc-{uuid4().hex}",
            tenant_id=tenant_id,
            corpus_id=corpus_id,
            filename=f"doc-{idx}.txt",
            content_type="text/plain",
            source="upload_file",
            ingest_source="upload_file",
            storage_path=None,
            metadata_json={},
            status="succeeded",
            created_at=now - timedelta(minutes=idx),
            updated_at=now - timedelta(minutes=idx),
        )
        for idx in range(3)
    ]

    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="UI Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector"}},
            )
        )
        session.add_all(docs)
        await grant_document_permissions(
            session=session,
            tenant_id=tenant_id,
            document_ids=[doc.id for doc in docs],
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
            response = await client.get("/v1/ui/documents?limit=2", headers=headers)
            assert response.status_code == 200
            data = response.json()["data"]
            assert len(data["items"]) == 2
            assert data["page"]["has_more"] is True
            assert data["page"]["next_cursor"]

            cursor = data["page"]["next_cursor"]
            response = await client.get(f"/v1/ui/documents?limit=2&cursor={cursor}", headers=headers)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["items"]

            bad_response = await client.get("/v1/ui/documents?cursor=bad", headers=headers)
            assert bad_response.status_code == 400
            error = bad_response.json()["error"]
            assert error["code"] == "INVALID_CURSOR"
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_ui_activity_timeline_items() -> None:
    tenant_id = f"t-ui-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
    )
    now = _utc_now()
    events = [
        AuditEvent(
            occurred_at=now - timedelta(minutes=1),
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id="k1",
            actor_role="admin",
            event_type="documents.ingest.enqueued",
            outcome="success",
            resource_type="document",
            resource_id="doc-1",
        ),
        AuditEvent(
            occurred_at=now - timedelta(minutes=2),
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id="k1",
            actor_role="admin",
            event_type="run.invoked",
            outcome="success",
            resource_type="run",
            resource_id="req-1",
        ),
    ]

    async with SessionLocal() as session:
        session.add_all(events)
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/ui/activity", headers=headers)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["items"]
            assert data["items"][0]["summary"]
    finally:
        await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_ui_reindex_action_returns_optimistic_payload(monkeypatch) -> None:
    tenant_id = f"t-ui-{uuid4().hex}"
    _raw_key, headers, user_id, key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="editor",
    )
    corpus_id = f"c-ui-{uuid4().hex}"
    document_id = f"doc-{uuid4().hex}"

    monkeypatch.setenv("INGEST_EXECUTION_MODE", "inline")
    get_settings.cache_clear()

    storage_path = write_text_to_storage(document_id, "reindex me")
    doc = Document(
        id=document_id,
        tenant_id=tenant_id,
        corpus_id=corpus_id,
        filename="reindex.txt",
        content_type="text/plain",
        source="upload_file",
        ingest_source="upload_file",
        storage_path=storage_path,
        metadata_json={},
        status="succeeded",
    )

    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Reindex Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector"}},
            )
        )
        session.add(doc)
        await grant_document_permission(
            session=session,
            tenant_id=tenant_id,
            document_id=document_id,
            principal_type="user",
            principal_id=user_id,
            permission="reindex",
            granted_by=key_id,
        )
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/ui/actions/reindex-document",
                headers=headers,
                json={"document_id": document_id, "idempotency_key": "ui-reindex-1"},
            )
            assert response.status_code == 202
            payload = response.json()["data"]
            assert payload["optimistic"]["patch"]["status"] == "queued"
            assert payload["action_id"]

        async with SessionLocal() as session:
            refreshed = await session.get(Document, document_id)
            assert refreshed.last_job_id
            assert refreshed.last_reindexed_at is not None
            action = await session.get(UiAction, payload["action_id"])
            assert action is not None
            assert action.status == "accepted"
    finally:
        path = Path(storage_path)
        if path.exists():
            path.unlink()
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()
