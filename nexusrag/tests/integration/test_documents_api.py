from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.domain.models import Chunk, Corpus, Document
from nexusrag.persistence.db import SessionLocal
from nexusrag.providers.retrieval.router import RetrievalRouter


@pytest.mark.asyncio
async def test_documents_upload_ingest_and_retrieve() -> None:
    app = create_app()
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"
    text = "Hello ingestion.\n\nThis paragraph should be retrievable."

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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents",
            headers={"X-Tenant-Id": tenant_id},
            data={"corpus_id": corpus_id},
            files={"file": ("test.txt", text, "text/plain")},
        )
        assert response.status_code == 200 or response.status_code == 202
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

        await db_session.execute(delete(Chunk).where(Chunk.corpus_id == corpus_id))
        await db_session.execute(delete(Document).where(Document.id == document_id))
        await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_documents_requires_tenant_header() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents")
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_documents_tenant_mismatch_returns_404() -> None:
    app = create_app()
    corpus_id = f"c-docs-{uuid4()}"
    tenant_id = "t1"

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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents",
            headers={"X-Tenant-Id": tenant_id},
            data={"corpus_id": corpus_id},
            files={"file": ("test.txt", "text", "text/plain")},
        )
        document_id = response.json()["document_id"]
        response = await client.get(
            f"/documents/{document_id}", headers={"X-Tenant-Id": "wrong"}
        )
        assert response.status_code == 404

    async with SessionLocal() as db_session:
        await db_session.execute(delete(Chunk).where(Chunk.corpus_id == corpus_id))
        await db_session.execute(delete(Document).where(Document.id == document_id))
        await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await db_session.commit()
