from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Chunk, Corpus, Document
from nexusrag.persistence.db import SessionLocal
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.providers.retrieval.router import RetrievalRouter
from nexusrag.tests.utils.auth import create_test_api_key


async def _create_corpus(corpus_id: str, tenant_id: str) -> None:
    # Insert a corpus for tenant-scoped ingestion tests.
    async with SessionLocal() as db_session:
        db_session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Docs Corpus",
                provider_config_json={
                    "retrieval": {"provider": "local_pgvector", "top_k_default": 5}
                },
            )
        )
        await db_session.commit()


async def _cleanup_document(corpus_id: str, document_id: str) -> None:
    # Keep tests idempotent by removing documents and chunks explicitly.
    async with SessionLocal() as db_session:
        await db_session.execute(delete(Chunk).where(Chunk.corpus_id == corpus_id))
        await db_session.execute(delete(Document).where(Document.id == document_id))
        await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await db_session.commit()


def _create_app_with_inline_ingest(monkeypatch) -> object:
    # Force inline ingestion for deterministic integration tests.
    monkeypatch.setenv("INGEST_EXECUTION_MODE", "inline")
    get_settings.cache_clear()
    return create_app()


def _utc_now() -> datetime:
    # Share a UTC clock helper for status updates in tests.
    return datetime.now(timezone.utc)


async def _wait_for_status(
    client: AsyncClient, headers: dict[str, str], document_id: str, target: str = "succeeded"
) -> str:
    # Poll the status endpoint until a target status appears.
    status = None
    for _ in range(30):
        resp = await client.get(f"/documents/{document_id}", headers=headers)
        assert resp.status_code == 200
        status = resp.json()["status"]
        if status == target:
            break
        await asyncio.sleep(0.1)
    return status


async def _auth_headers(tenant_id: str, role: str) -> dict[str, str]:
    # Provision a scoped API key for document API tests.
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role=role,
    )
    return headers


@pytest.mark.asyncio
async def test_documents_upload_ingest_and_retrieve(monkeypatch) -> None:
    app = _create_app_with_inline_ingest(monkeypatch)
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Hello ingestion.\n\nThis paragraph should be retrievable."

    await _create_corpus(corpus_id, tenant_id)
    # Use an editor key to allow document ingestion endpoints.
    headers = await _auth_headers(tenant_id, "editor")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents",
            headers=headers,
            data={"corpus_id": corpus_id},
            files={"file": ("test.txt", text, "text/plain")},
        )
        assert response.status_code == 202
        payload = response.json()
        document_id = payload["document_id"]
        assert payload["job_id"]
        assert payload["status_url"].endswith(document_id)

        status = await _wait_for_status(client, headers, document_id)
        assert status == "succeeded"

    async with SessionLocal() as db_session:
        retriever = RetrievalRouter(db_session)
        results = await retriever.retrieve(tenant_id, corpus_id, "retrievable", top_k=3)
        assert results
        assert any("retrievable" in item["text"] for item in results)

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_text_ingest_is_idempotent(monkeypatch) -> None:
    app = _create_app_with_inline_ingest(monkeypatch)
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Idempotent ingestion text."
    document_id = f"doc-{uuid4()}"

    await _create_corpus(corpus_id, tenant_id)
    # Use an editor key to allow document ingestion endpoints.
    headers = await _auth_headers(tenant_id, "editor")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": text, "document_id": document_id},
        )
        assert response.status_code == 202

        status = await _wait_for_status(client, headers, document_id)
        assert status == "succeeded"

        async with SessionLocal() as db_session:
            first_count = await documents_repo.count_chunks(db_session, document_id)

        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": text, "document_id": document_id},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "succeeded"

    async with SessionLocal() as db_session:
        # Confirm the idempotent request did not duplicate chunks.
        chunk_count = await documents_repo.count_chunks(db_session, document_id)
        assert chunk_count == first_count

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_text_ingest_idempotent_while_queued(monkeypatch) -> None:
    app = _create_app_with_inline_ingest(monkeypatch)
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Queued idempotency."
    document_id = f"doc-{uuid4()}"

    await _create_corpus(corpus_id, tenant_id)
    # Use an editor key to allow document ingestion endpoints.
    headers = await _auth_headers(tenant_id, "editor")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": text, "document_id": document_id},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        async with SessionLocal() as db_session:
            # Force queued state to validate idempotent enqueue behavior.
            doc = await documents_repo.get_document(db_session, tenant_id, document_id)
            assert doc is not None
            doc.status = "queued"
            doc.processing_started_at = None
            doc.completed_at = None
            await db_session.commit()

        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": text, "document_id": document_id},
        )
        assert response.status_code == 200
        assert response.json()["job_id"] == job_id

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_delete_removes_chunks(monkeypatch) -> None:
    app = _create_app_with_inline_ingest(monkeypatch)
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Delete me."

    await _create_corpus(corpus_id, tenant_id)
    # Use an editor key to allow document ingestion endpoints.
    headers = await _auth_headers(tenant_id, "editor")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": text},
        )
        assert response.status_code == 202
        document_id = response.json()["document_id"]

        status = await _wait_for_status(client, headers, document_id)
        assert status == "succeeded"

        response = await client.delete(
            f"/documents/{document_id}", headers=headers
        )
        assert response.status_code == 204

        response = await client.get(
            f"/documents/{document_id}", headers=headers
        )
        assert response.status_code == 404

    async with SessionLocal() as db_session:
        retriever = RetrievalRouter(db_session)
        results = await retriever.retrieve(tenant_id, corpus_id, "Delete", top_k=3)
        assert results == []

        await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_documents_reindex_updates_chunking(monkeypatch) -> None:
    app = _create_app_with_inline_ingest(monkeypatch)
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "A" * 2600

    await _create_corpus(corpus_id, tenant_id)
    # Use an editor key to allow document ingestion endpoints.
    headers = await _auth_headers(tenant_id, "editor")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": text},
        )
        document_id = response.json()["document_id"]
        assert response.status_code == 202

        status = await _wait_for_status(client, headers, document_id)
        assert status == "succeeded"

        async with SessionLocal() as db_session:
            original_chunks = await documents_repo.count_chunks(db_session, document_id)

        response = await client.post(
            f"/documents/{document_id}/reindex",
            headers=headers,
            json={"chunk_size_chars": 800, "chunk_overlap_chars": 100},
        )
        assert response.status_code == 202

        status = await _wait_for_status(client, headers, document_id)
        assert status == "succeeded"

        async with SessionLocal() as db_session:
            reindexed_chunks = await documents_repo.count_chunks(db_session, document_id)
            assert reindexed_chunks != original_chunks

        response = await client.get(
            f"/documents/{document_id}", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["last_reindexed_at"] is not None

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_failure_sets_failure_reason(monkeypatch) -> None:
    app = _create_app_with_inline_ingest(monkeypatch)
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Failure case."

    await _create_corpus(corpus_id, tenant_id)
    # Use an editor key to allow document ingestion endpoints.
    headers = await _auth_headers(tenant_id, "editor")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers=headers,
            json={
                "corpus_id": corpus_id,
                "text": text,
                "chunk_size_chars": 100,
                "chunk_overlap_chars": 100,
            },
        )
        assert response.status_code == 202
        document_id = response.json()["document_id"]

        status = await _wait_for_status(client, headers, document_id, target="failed")
        assert status == "failed"

        resp = await client.get(
            f"/documents/{document_id}", headers=headers
        )
        assert resp.status_code == 200
        assert "chunk_overlap_chars" in (resp.json().get("failure_reason") or "")

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_delete_while_processing_returns_409(monkeypatch) -> None:
    app = _create_app_with_inline_ingest(monkeypatch)
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Processing delete."

    await _create_corpus(corpus_id, tenant_id)
    # Use an editor key to allow document ingestion endpoints.
    headers = await _auth_headers(tenant_id, "editor")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": text},
        )
        assert response.status_code == 202
        document_id = response.json()["document_id"]

        async with SessionLocal() as db_session:
            # Simulate an in-flight document to validate delete rejection.
            doc = await documents_repo.get_document(db_session, tenant_id, document_id)
            assert doc is not None
            doc.status = "processing"
            doc.processing_started_at = _utc_now()
            doc.completed_at = None
            await db_session.commit()

        response = await client.delete(
            f"/documents/{document_id}", headers=headers
        )
        assert response.status_code == 409

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_tenant_mismatch_returns_404(monkeypatch) -> None:
    app = _create_app_with_inline_ingest(monkeypatch)
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"

    await _create_corpus(corpus_id, tenant_id)
    # Create tenant-scoped keys to validate isolation semantics.
    headers = await _auth_headers(tenant_id, "editor")
    wrong_headers = await _auth_headers("wrong", "editor")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers=headers,
            json={"corpus_id": corpus_id, "text": "text"},
        )
        document_id = response.json()["document_id"]
        assert response.status_code == 202

        response = await client.delete(
            f"/documents/{document_id}", headers=wrong_headers
        )
        assert response.status_code == 404

        response = await client.post(
            f"/documents/{document_id}/reindex",
            headers=wrong_headers,
        )
        assert response.status_code == 404

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_requires_auth() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents")
        assert response.status_code == 401
