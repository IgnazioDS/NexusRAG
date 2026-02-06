from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.domain.models import Chunk, Corpus, Document
from nexusrag.persistence.db import SessionLocal
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.providers.retrieval.router import RetrievalRouter


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


@pytest.mark.asyncio
async def test_documents_upload_ingest_and_retrieve() -> None:
    app = create_app()
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Hello ingestion.\n\nThis paragraph should be retrievable."

    await _create_corpus(corpus_id, tenant_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents",
            headers={"X-Tenant-Id": tenant_id},
            data={"corpus_id": corpus_id},
            files={"file": ("test.txt", text, "text/plain")},
        )
        assert response.status_code == 202
        document_id = response.json()["document_id"]

        # Poll until ingestion succeeds to keep the test deterministic.
        status = None
        for _ in range(30):
            resp = await client.get(
                f"/documents/{document_id}", headers={"X-Tenant-Id": tenant_id}
            )
            assert resp.status_code == 200
            status = resp.json()["status"]
            if status == "succeeded":
                break
            await asyncio.sleep(0.1)
        assert status == "succeeded"

    async with SessionLocal() as db_session:
        retriever = RetrievalRouter(db_session)
        results = await retriever.retrieve(tenant_id, corpus_id, "retrievable", top_k=3)
        assert results
        assert any("retrievable" in item["text"] for item in results)

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_text_ingest_is_idempotent() -> None:
    app = create_app()
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Idempotent ingestion text."
    document_id = f"doc-{uuid4()}"

    await _create_corpus(corpus_id, tenant_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers={"X-Tenant-Id": tenant_id},
            json={"corpus_id": corpus_id, "text": text, "document_id": document_id},
        )
        assert response.status_code == 201
        first_count = response.json()["num_chunks"]

        response = await client.post(
            "/documents/text",
            headers={"X-Tenant-Id": tenant_id},
            json={"corpus_id": corpus_id, "text": text, "document_id": document_id},
        )
        assert response.status_code == 200
        assert response.json()["num_chunks"] == first_count

    async with SessionLocal() as db_session:
        # Confirm the idempotent request did not duplicate chunks.
        chunk_count = await documents_repo.count_chunks(db_session, document_id)
        assert chunk_count == first_count

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_delete_removes_chunks() -> None:
    app = create_app()
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Delete me."

    await _create_corpus(corpus_id, tenant_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers={"X-Tenant-Id": tenant_id},
            json={"corpus_id": corpus_id, "text": text},
        )
        document_id = response.json()["document_id"]

        response = await client.delete(
            f"/documents/{document_id}", headers={"X-Tenant-Id": tenant_id}
        )
        assert response.status_code == 204

        response = await client.get(
            f"/documents/{document_id}", headers={"X-Tenant-Id": tenant_id}
        )
        assert response.status_code == 404

    async with SessionLocal() as db_session:
        retriever = RetrievalRouter(db_session)
        results = await retriever.retrieve(tenant_id, corpus_id, "Delete", top_k=3)
        assert results == []

        await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_documents_reindex_updates_chunking() -> None:
    app = create_app()
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "A" * 2600

    await _create_corpus(corpus_id, tenant_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers={"X-Tenant-Id": tenant_id},
            json={"corpus_id": corpus_id, "text": text},
        )
        document_id = response.json()["document_id"]
        original_chunks = response.json()["num_chunks"]

        response = await client.post(
            f"/documents/{document_id}/reindex",
            headers={"X-Tenant-Id": tenant_id},
            json={"chunk_size_chars": 800, "chunk_overlap_chars": 100},
        )
        assert response.status_code == 200
        assert response.json()["num_chunks"] != original_chunks

        response = await client.get(
            f"/documents/{document_id}", headers={"X-Tenant-Id": tenant_id}
        )
        assert response.status_code == 200
        assert response.json()["last_reindexed_at"] is not None

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_tenant_mismatch_returns_404() -> None:
    app = create_app()
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"

    await _create_corpus(corpus_id, tenant_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/text",
            headers={"X-Tenant-Id": tenant_id},
            json={"corpus_id": corpus_id, "text": "text"},
        )
        document_id = response.json()["document_id"]

        response = await client.delete(
            f"/documents/{document_id}", headers={"X-Tenant-Id": "wrong"}
        )
        assert response.status_code == 404

        response = await client.post(
            f"/documents/{document_id}/reindex",
            headers={"X-Tenant-Id": "wrong"},
        )
        assert response.status_code == 404

    await _cleanup_document(corpus_id, document_id)


@pytest.mark.asyncio
async def test_documents_requires_tenant_header() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents")
        assert response.status_code == 400
