from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Document, DocumentLabel, DocumentPermission
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.ingest import queue as ingest_queue
from nexusrag.tests.utils.auth import create_test_api_key


def _utc_now() -> datetime:
    # Use UTC timestamps to align with ops windowing logic.
    return datetime.now(timezone.utc)


async def _seed_document(
    *,
    status: str,
    queued_at: datetime | None = None,
    processing_started_at: datetime | None = None,
    completed_at: datetime | None = None,
    failure_reason: str | None = None,
) -> str:
    # Insert documents with explicit timestamps to validate ops aggregation.
    document_id = f"doc-{uuid4()}"
    async with SessionLocal() as session:
        session.add(
            Document(
                id=document_id,
                tenant_id="t-ops",
                corpus_id="c-ops",
                filename="ops.txt",
                content_type="text/plain",
                source="raw_text",
                ingest_source="raw_text",
                status=status,
                queued_at=queued_at,
                processing_started_at=processing_started_at,
                completed_at=completed_at,
                failure_reason=failure_reason,
            )
        )
        await session.commit()
    return document_id


async def _cleanup_documents() -> None:
    # Keep ops tests isolated from other integration runs.
    async with SessionLocal() as session:
        await session.execute(
            DocumentPermission.__table__.delete().where(DocumentPermission.tenant_id == "t-ops")
        )
        await session.execute(
            DocumentLabel.__table__.delete().where(DocumentLabel.tenant_id == "t-ops")
        )
        await session.execute(
            Document.__table__.delete().where(Document.tenant_id == "t-ops")
        )
        await session.commit()


async def _admin_headers() -> dict[str, str]:
    # Use an admin key to access ops endpoints in tests.
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t-ops",
        role="admin",
    )
    return headers


@pytest.mark.asyncio
async def test_ops_health_heartbeat_degraded(monkeypatch) -> None:
    # Ensure the ops health endpoint degrades when heartbeat is missing.
    monkeypatch.setenv("INGEST_EXECUTION_MODE", "queue")
    get_settings.cache_clear()
    app = create_app()
    headers = await _admin_headers()

    redis = await ingest_queue.get_redis_pool()
    await redis.delete(ingest_queue.WORKER_HEARTBEAT_KEY)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/health", headers=headers)
    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert "worker_heartbeat_age_s" in payload
    assert "queue_depth" in payload


@pytest.mark.asyncio
async def test_ops_health_heartbeat_ok(monkeypatch) -> None:
    # Report healthy status when the worker heartbeat is recent.
    monkeypatch.setenv("INGEST_EXECUTION_MODE", "queue")
    get_settings.cache_clear()
    app = create_app()
    headers = await _admin_headers()

    await ingest_queue.set_worker_heartbeat(timestamp=_utc_now() - timedelta(seconds=5))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/health", headers=headers)
    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["db"] in {"ok", "degraded"}
    assert payload["redis"] in {"ok", "degraded"}


@pytest.mark.asyncio
async def test_ops_health_degrades_when_redis_missing(monkeypatch) -> None:
    # Simulate Redis failures to confirm graceful degradation.
    monkeypatch.setenv("INGEST_EXECUTION_MODE", "queue")
    get_settings.cache_clear()
    app = create_app()
    headers = await _admin_headers()

    async def _no_queue_depth() -> int | None:
        return None

    async def _no_heartbeat() -> datetime | None:
        return None

    monkeypatch.setattr(ingest_queue, "get_queue_depth", _no_queue_depth)
    monkeypatch.setattr(ingest_queue, "get_worker_heartbeat", _no_heartbeat)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/health", headers=headers)
    payload = response.json()
    assert response.status_code == 200
    assert payload["redis"] == "degraded"


@pytest.mark.asyncio
async def test_ops_ingestion_returns_counts(monkeypatch) -> None:
    # Validate ingestion aggregates and queue depth keys.
    monkeypatch.setenv("INGEST_EXECUTION_MODE", "queue")
    get_settings.cache_clear()
    app = create_app()
    headers = await _admin_headers()

    now = _utc_now()
    queued_id = await _seed_document(status="queued", queued_at=now - timedelta(hours=1))
    processing_id = await _seed_document(
        status="processing",
        processing_started_at=now - timedelta(minutes=30),
    )
    succeeded_id = await _seed_document(
        status="succeeded",
        processing_started_at=now - timedelta(minutes=10),
        completed_at=now - timedelta(minutes=5),
    )
    failed_id = await _seed_document(
        status="failed",
        processing_started_at=now - timedelta(minutes=20),
        completed_at=now - timedelta(minutes=15),
        failure_reason="chunk_overlap_chars must be smaller than chunk_size_chars",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/ingestion?hours=24", headers=headers)
    payload = response.json()
    assert response.status_code == 200
    assert payload["documents"]["queued"] >= 1
    assert payload["documents"]["processing"] >= 1
    assert payload["documents"]["succeeded"] >= 1
    assert payload["documents"]["failed"] >= 1
    assert "queue_depth" in payload
    assert payload["durations_ms"]["max"] is not None
    assert any(
        item["reason"] == "INGEST_VALIDATION_ERROR"
        for item in payload["top_failure_reasons"]
    )

    await _cleanup_documents()
    assert queued_id and processing_id and succeeded_id and failed_id


@pytest.mark.asyncio
async def test_ops_metrics_shape(monkeypatch) -> None:
    # Ensure metrics endpoint exposes expected counters and gauges.
    monkeypatch.setenv("INGEST_EXECUTION_MODE", "queue")
    get_settings.cache_clear()
    app = create_app()
    headers = await _admin_headers()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/metrics", headers=headers)
    payload = response.json()
    assert response.status_code == 200
    assert "counters" in payload
    assert "gauges" in payload
    assert "nexusrag_ingest_enqueued_total" in payload["counters"]
    assert "nexusrag_ingest_queue_depth" in payload["gauges"]
