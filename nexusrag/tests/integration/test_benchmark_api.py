from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.domain.models import BenchmarkRun
from nexusrag.persistence.db import SessionLocal


async def _clear_runs() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(BenchmarkRun))
        await session.commit()


async def _get_benchmark_latest() -> tuple[int, dict]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/benchmark-latest")
    return resp.status_code, resp.json()


@pytest.mark.asyncio
async def test_benchmark_latest_pending_when_empty() -> None:
    await _clear_runs()
    status, body = await _get_benchmark_latest()
    assert status == 200
    assert body["system"] == "nexusrag"
    assert body["schema_version"] == 1
    assert body["status"] == "pending"
    assert body["latest"] is None
    assert body["previous_run"] is None


@pytest.mark.asyncio
async def test_benchmark_latest_returns_latest_and_previous() -> None:
    await _clear_runs()
    async with SessionLocal() as session:
        session.add_all(
            [
                BenchmarkRun(
                    id=uuid4(),
                    fixture_version="benchmark-v1",
                    embedding_provider="fake",
                    generated_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
                    case_count=10,
                    metrics={"recall_at_5": 0.5},
                ),
                BenchmarkRun(
                    id=uuid4(),
                    fixture_version="benchmark-v1",
                    embedding_provider="fake",
                    generated_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
                    case_count=10,
                    metrics={"recall_at_5": 0.7},
                ),
            ]
        )
        await session.commit()
    try:
        status, body = await _get_benchmark_latest()
        assert status == 200
        assert body["status"] == "ok"
        assert body["latest"]["metrics"]["recall_at_5"] == 0.7
        assert body["latest"]["embedding_provider"] == "fake"
        assert body["previous_run"]["metrics"]["recall_at_5"] == 0.5
    finally:
        await _clear_runs()
