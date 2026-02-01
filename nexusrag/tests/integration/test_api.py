from __future__ import annotations

import pytest
from httpx import AsyncClient

from nexusrag.apps.api.main import create_app
from nexusrag.apps.api.deps import get_db
from nexusrag.core.errors import ProviderConfigError


class DummySession:
    async def commit(self) -> None:
        return None


async def override_get_db():
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
            body = ""
            async for line in response.aiter_lines():
                body += line

    assert "provider_config_error" in body
    assert "error" in body
