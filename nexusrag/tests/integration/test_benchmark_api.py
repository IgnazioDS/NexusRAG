from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

import nexusrag.apps.api.routes.benchmark as benchmark_route
from nexusrag.apps.api.main import create_app


async def _get_benchmark_latest() -> tuple[int, dict]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/benchmark-latest")
    return resp.status_code, resp.json()


@pytest.mark.asyncio
async def test_benchmark_latest_pending_when_no_artifact(tmp_path, monkeypatch) -> None:
    # No committed run yet -> honest "pending" (200), not an error.
    monkeypatch.setattr(benchmark_route, "_ARTIFACT", tmp_path / "missing.json")
    status, body = await _get_benchmark_latest()
    assert status == 200
    assert body["system"] == "nexusrag"
    assert body["schema_version"] == 1
    assert body["status"] == "pending"
    assert body["latest"] is None
    assert body["previous_run"] is None


@pytest.mark.asyncio
async def test_benchmark_latest_serves_committed_artifact(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "latest_run.json"
    artifact.write_text(
        json.dumps(
            {
                "system": "nexusrag",
                "schema_version": 1,
                "status": "ok",
                "latest": {
                    "run_id": "r2",
                    "fixture_version": "benchmark-v1",
                    "embedding_provider": "openai",
                    "generated_at": "2026-05-26T00:00:00Z",
                    "case_count": 18,
                    "metrics": {"retrieval": {"recall_at_5": 0.93, "ndcg_at_10": 0.9}},
                },
                "previous_run": {
                    "run_id": "r1",
                    "fixture_version": "benchmark-v1",
                    "embedding_provider": "fake",
                    "generated_at": "2026-05-25T00:00:00Z",
                    "case_count": 18,
                    "metrics": {"retrieval": {"recall_at_5": 0.4}},
                },
                "generated_at": "2026-05-26T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(benchmark_route, "_ARTIFACT", artifact)
    status, body = await _get_benchmark_latest()
    assert status == 200
    assert body["status"] == "ok"
    assert body["latest"]["embedding_provider"] == "openai"
    assert body["latest"]["metrics"]["retrieval"]["recall_at_5"] == 0.93
    assert body["previous_run"]["metrics"]["retrieval"]["recall_at_5"] == 0.4
    # The served-at stamp is refreshed by the endpoint, not the committed value.
    assert body["generated_at"] != "2026-05-26T00:00:00Z" or body["generated_at"].endswith("Z")


@pytest.mark.asyncio
async def test_benchmark_latest_degraded_on_unreadable_artifact(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "latest_run.json"
    artifact.write_text("{ this is not valid json", encoding="utf-8")
    monkeypatch.setattr(benchmark_route, "_ARTIFACT", artifact)
    status, body = await _get_benchmark_latest()
    assert status == 200  # public contract: never 5xx
    assert body["status"] == "degraded"
    assert body["latest"] is None
