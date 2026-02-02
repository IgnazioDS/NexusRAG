from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.domain.models import Corpus
from nexusrag.persistence.db import SessionLocal


@pytest.mark.asyncio
async def test_corpora_list_and_get() -> None:
    app = create_app()
    corpus_id = f"c-list-{uuid4()}"
    provider_config_json = {"retrieval": {"provider": "local_pgvector", "top_k_default": 5}}

    async with SessionLocal() as db_session:
        # Insert a corpus directly to avoid relying on external seed steps.
        db_session.add(
            Corpus(
                id=corpus_id,
                tenant_id="t1",
                name="List Corpus",
                provider_config_json=provider_config_json,
            )
        )
        await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/corpora", headers={"X-Tenant-Id": "t1"})
        assert response.status_code == 200
        payload = response.json()
        assert any(item["id"] == corpus_id for item in payload)

        response = await client.get(f"/corpora/{corpus_id}", headers={"X-Tenant-Id": "t1"})
        assert response.status_code == 200
        assert response.json()["id"] == corpus_id

        response = await client.get(f"/corpora/{corpus_id}", headers={"X-Tenant-Id": "wrong"})
        assert response.status_code == 404

    async with SessionLocal() as db_session:
        await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_corpora_patch_validation_and_update() -> None:
    app = create_app()
    corpus_id = f"c-patch-{uuid4()}"
    provider_config_json = {"retrieval": {"provider": "local_pgvector", "top_k_default": 5}}

    async with SessionLocal() as db_session:
        # Seed a row so the patch endpoint can exercise updates.
        db_session.add(
            Corpus(
                id=corpus_id,
                tenant_id="t1",
                name="Patch Corpus",
                provider_config_json=provider_config_json,
            )
        )
        await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/corpora/{corpus_id}",
            headers={"X-Tenant-Id": "t1"},
            json={"provider_config_json": {"retrieval": {"provider": "nope"}}},
        )
        assert response.status_code == 422

        response = await client.patch(
            f"/corpora/{corpus_id}",
            headers={"X-Tenant-Id": "t1"},
            json={
                "provider_config_json": {
                    "retrieval": {
                        "provider": "aws_bedrock_kb",
                        "knowledge_base_id": "KB123",
                        "region": "us-east-1",
                        "top_k_default": 5,
                    }
                }
            },
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["provider_config_json"]["retrieval"]["provider"] == "aws_bedrock_kb"

        response = await client.patch(
            f"/corpora/{corpus_id}",
            headers={"X-Tenant-Id": "t1"},
            json={"provider_config_json": {}},
        )
        assert response.status_code == 200
        normalized = response.json()["provider_config_json"]["retrieval"]
        assert normalized["provider"] == "local_pgvector"

    async with SessionLocal() as db_session:
        await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await db_session.commit()
