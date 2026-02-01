from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from nexusrag.apps.api.main import create_app
from nexusrag.apps.api.deps import get_db
from nexusrag.core.errors import ProviderConfigError


class DummySession:
    # Minimal async session stub to satisfy route dependencies in integration-ish tests.
    async def commit(self) -> None:
        return None


async def override_get_db():
    # Override the DB dependency to avoid relying on a real database.
    yield DummySession()


@pytest.mark.asyncio
async def test_health() -> None:
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_run_emits_error_when_vertex_missing(monkeypatch) -> None:
    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    # Force missing Vertex configuration to validate error mapping without external calls.
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)

    async def noop(*args, **kwargs):
        return None

    async def run_graph_raise(*args, **kwargs):
        raise ProviderConfigError("Vertex AI configuration missing: set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION.")

    from nexusrag.apps.api.routes import run as run_route

    monkeypatch.setattr(run_route.sessions_repo, "upsert_session", noop)
    monkeypatch.setattr(run_route.messages_repo, "add_message", noop)
    monkeypatch.setattr(run_route.checkpoints_repo, "add_checkpoint", noop)
    monkeypatch.setattr(run_route, "run_graph", run_graph_raise)

    payload = {
        "session_id": "s1",
        "tenant_id": "t1",
        "corpus_id": "c1",
        "message": "Hello?",
        "top_k": 3,
        "audio": False,
    }

    async with AsyncClient(app=app, base_url="http://test") as client:
        async with client.stream("POST", "/run", json=payload) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = []
            async for line in response.aiter_lines():
                if line:
                    lines.append(line)
                if len(lines) >= 2:
                    break

    # Validate SSE framing invariants: event line then data line.
    assert lines[0].startswith("event: message")
    assert lines[1].startswith("data: ")
    payload_json = json.loads(lines[1].removeprefix("data: ").strip())
    assert payload_json["type"] == "error"
    assert payload_json["data"]["code"] == "VERTEX_CONFIG_MISSING"
    # Session id should be echoed for traceability during debugging.
    assert payload_json["session_id"] == "s1"
    assert payload_json.get("request_id")
