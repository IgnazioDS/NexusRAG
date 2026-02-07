from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api.main import create_app
from nexusrag.apps.api import rate_limit
from nexusrag.core.config import get_settings
from nexusrag.domain.models import AuditEvent, Corpus
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key


def _tenant_id() -> str:
    # Use unique tenant ids to avoid cross-test interference.
    return f"t-rl-{uuid4().hex}"


def _apply_rate_limit_env(monkeypatch, **overrides: str) -> None:
    # Set rate limit env vars and reset cached settings/limiter state.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()


def _build_app(monkeypatch, **env_overrides: str):
    _apply_rate_limit_env(monkeypatch, **env_overrides)
    return create_app()


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    # Clear settings cache between tests to avoid leaking env overrides.
    yield
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()


async def _create_corpus(corpus_id: str, tenant_id: str) -> None:
    # Seed a corpus for /run requests without external dependencies.
    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Rate Limit Corpus",
                provider_config_json={
                    "retrieval": {"provider": "local_pgvector", "top_k_default": 5}
                },
            )
        )
        await session.commit()


async def _cleanup_corpus(corpus_id: str) -> None:
    # Remove seeded corpora after rate limit integration tests.
    async with SessionLocal() as session:
        await session.execute(delete(Corpus).where(Corpus.id == corpus_id))
        await session.commit()


@pytest.mark.asyncio
async def test_rate_limit_burst_then_throttle(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    app = _build_app(
        monkeypatch,
        RL_KEY_READ_RPS=1,
        RL_KEY_READ_BURST=2,
        RL_TENANT_READ_RPS=50,
        RL_TENANT_READ_BURST=100,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers)

    assert response.status_code == 429
    payload = response.json()["detail"]
    assert payload["code"] == "RATE_LIMITED"
    assert payload["scope"] == "api_key"
    assert payload["route_class"] == "read"
    assert "retry_after_ms" in payload
    assert response.headers.get("Retry-After")
    assert response.headers.get("X-RateLimit-Scope") == "api_key"
    assert response.headers.get("X-RateLimit-Route-Class") == "read"
    assert response.headers.get("X-RateLimit-Retry-After-Ms")

    async with SessionLocal() as session:
        result = await session.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.event_type == "security.rate_limited",
            )
        )
        assert result.scalars().first() is not None


@pytest.mark.asyncio
async def test_run_weighting_is_stricter_than_read(monkeypatch) -> None:
    tenant_id = _tenant_id()
    corpus_id = f"c-rl-{uuid4().hex}"
    await _create_corpus(corpus_id, tenant_id)

    monkeypatch.setenv("LLM_PROVIDER", "fake")
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    app = _build_app(
        monkeypatch,
        RL_KEY_RUN_RPS=1,
        RL_KEY_RUN_BURST=3,
        RL_TENANT_RUN_RPS=50,
        RL_TENANT_RUN_BURST=100,
        RL_KEY_READ_RPS=5,
        RL_KEY_READ_BURST=10,
        RL_TENANT_READ_RPS=50,
        RL_TENANT_READ_BURST=100,
    )

    payload = {
        "session_id": f"s-rl-{uuid4().hex}",
        "corpus_id": corpus_id,
        "message": "Hello",
        "top_k": 1,
        "audio": False,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("POST", "/run", json=payload, headers=headers) as response:
            assert response.status_code == 200
        response = await client.post("/run", json=payload, headers=headers)
        assert response.status_code == 429

        response = await client.get("/documents", headers=headers)
        assert response.status_code == 200

    await _cleanup_corpus(corpus_id)


@pytest.mark.asyncio
async def test_tenant_limit_blocks_across_keys(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _raw_key, headers_a, _user_id_a, _key_id_a = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    _raw_key, headers_b, _user_id_b, _key_id_b = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )

    app = _build_app(
        monkeypatch,
        RL_KEY_READ_RPS=5,
        RL_KEY_READ_BURST=10,
        RL_TENANT_READ_RPS=1,
        RL_TENANT_READ_BURST=2,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers_a)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers_b)
        assert response.status_code == 200
        response = await client.get("/documents", headers=headers_b)
        assert response.status_code == 429
        assert response.headers.get("X-RateLimit-Scope") == "tenant"


@pytest.mark.asyncio
async def test_fail_open_allows_request_with_degraded_header(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    app = _build_app(
        monkeypatch,
        REDIS_URL="redis://localhost:9999/0",
        RL_FAIL_MODE="open",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)

    assert response.status_code == 200
    assert response.headers.get("X-RateLimit-Status") == "degraded"


@pytest.mark.asyncio
async def test_fail_closed_returns_503(monkeypatch) -> None:
    tenant_id = _tenant_id()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
    )
    app = _build_app(
        monkeypatch,
        REDIS_URL="redis://localhost:9999/0",
        RL_FAIL_MODE="closed",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents", headers=headers)

    assert response.status_code == 503
    payload = response.json()["detail"]
    assert payload["code"] == "RATE_LIMIT_UNAVAILABLE"
