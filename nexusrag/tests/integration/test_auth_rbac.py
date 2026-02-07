from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Chunk, Corpus, Document
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key


def _utc_now() -> datetime:
    # Use UTC timestamps for deterministic status fields.
    return datetime.now(timezone.utc)


async def _create_corpus(corpus_id: str, tenant_id: str) -> None:
    # Seed a corpus row for auth and RBAC integration tests.
    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Auth Corpus",
                provider_config_json={
                    "retrieval": {"provider": "local_pgvector", "top_k_default": 5}
                },
            )
        )
        await session.commit()


async def _create_document(document_id: str, corpus_id: str, tenant_id: str) -> None:
    # Insert a document row for tenant isolation checks without ingestion.
    async with SessionLocal() as session:
        session.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                corpus_id=corpus_id,
                filename="auth.txt",
                content_type="text/plain",
                source="raw_text",
                ingest_source="raw_text",
                status="succeeded",
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )
        await session.commit()


async def _cleanup_auth_rows(*, corpus_id: str, document_id: str | None = None) -> None:
    # Remove seeded rows to keep auth tests isolated.
    async with SessionLocal() as session:
        if document_id:
            await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            await session.execute(delete(Document).where(Document.id == document_id))
        else:
            await session.execute(delete(Chunk).where(Chunk.corpus_id == corpus_id))
            await session.execute(delete(Document).where(Document.corpus_id == corpus_id))
        await session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await session.commit()


def _create_app_inline(monkeypatch) -> object:
    # Force inline ingestion so document tests run without a worker.
    monkeypatch.setenv("INGEST_EXECUTION_MODE", "inline")
    get_settings.cache_clear()
    return create_app()


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth() -> None:
    # Clear cached settings so auth defaults are enforced.
    get_settings.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reader_key_can_access_get_documents_and_run(monkeypatch) -> None:
    app = _create_app_inline(monkeypatch)
    corpus_id = f"c-auth-{uuid4()}"
    await _create_corpus(corpus_id, "t1")
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="reader",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200

        payload = {
            "session_id": f"s-{uuid4()}",
            "corpus_id": corpus_id,
            "message": "Hello",
            "top_k": 3,
            "audio": False,
        }
        async with client.stream("POST", "/run", json=payload, headers=headers) as resp:
            assert resp.status_code == 200

    await _cleanup_auth_rows(corpus_id=corpus_id)


@pytest.mark.asyncio
async def test_reader_key_cannot_mutate_documents_or_corpora(monkeypatch) -> None:
    app = _create_app_inline(monkeypatch)
    corpus_id = f"c-auth-{uuid4()}"
    await _create_corpus(corpus_id, "t1")
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="reader",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": "blocked"},
        )
        assert response.status_code == 403

        response = await client.patch(
            f"/corpora/{corpus_id}",
            headers=headers,
            json={"name": "blocked"},
        )
        assert response.status_code == 403

    await _cleanup_auth_rows(corpus_id=corpus_id)


@pytest.mark.asyncio
async def test_editor_key_can_mutate_documents_and_corpora(monkeypatch) -> None:
    app = _create_app_inline(monkeypatch)
    corpus_id = f"c-auth-{uuid4()}"
    await _create_corpus(corpus_id, "t1")
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="editor",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/corpora/{corpus_id}",
            headers=headers,
            json={"name": "Updated"},
        )
        assert response.status_code == 200

        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": "allowed"},
        )
        assert response.status_code == 202
        document_id = response.json()["document_id"]

    await _cleanup_auth_rows(corpus_id=corpus_id, document_id=document_id)


@pytest.mark.asyncio
async def test_admin_key_can_access_ops(monkeypatch) -> None:
    app = _create_app_inline(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="admin",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/health", headers=headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_revoked_key_is_unauthorized(monkeypatch) -> None:
    app = _create_app_inline(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="reader",
        key_revoked=True,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tenant_isolation_by_key(monkeypatch) -> None:
    app = _create_app_inline(monkeypatch)
    corpus_id = f"c-auth-{uuid4()}"
    document_id = f"doc-auth-{uuid4()}"
    await _create_corpus(corpus_id, "t2")
    await _create_document(document_id, corpus_id, "t2")

    _raw_key, t1_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="reader",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/documents/{document_id}", headers=t1_headers)
        assert response.status_code == 404

    await _cleanup_auth_rows(corpus_id=corpus_id, document_id=document_id)


@pytest.mark.asyncio
async def test_dev_bypass_allows_legacy_tenant_header(monkeypatch) -> None:
    # Enable dev bypass to allow X-Tenant-Id without Authorization.
    monkeypatch.setenv("AUTH_DEV_BYPASS", "true")
    get_settings.cache_clear()
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers={"X-Tenant-Id": "t1"})
    assert response.status_code == 200
