from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.apps.api import rate_limit
from nexusrag.core.config import get_settings
from nexusrag.domain.models import AuditEvent, Corpus, TenantFeatureOverride, TenantPlanAssignment
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.entitlements import (
    FEATURE_RETRIEVAL_AWS,
    FEATURE_TTS,
    reset_entitlements_cache,
)
from nexusrag.tests.utils.auth import create_test_api_key


def _apply_env(monkeypatch) -> None:
    # Force fake providers to avoid external dependencies during entitlement tests.
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TTS_PROVIDER", "fake")
    monkeypatch.setenv("AUDIO_BASE_URL", "http://test")
    # Keep rate limits high to avoid throttling during rapid entitlement checks.
    monkeypatch.setenv("RL_KEY_RUN_RPS", "100")
    monkeypatch.setenv("RL_KEY_RUN_BURST", "200")
    monkeypatch.setenv("RL_TENANT_RUN_RPS", "100")
    monkeypatch.setenv("RL_TENANT_RUN_BURST", "200")
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()


@pytest.fixture(autouse=True)
def _reset_caches() -> None:
    # Reset settings + entitlement caches between tests to avoid leakage.
    yield
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()
    reset_entitlements_cache()


async def _seed_corpus(tenant_id: str, corpus_id: str, provider_config_json: dict) -> None:
    # Insert corpus configs used by entitlement-gated run requests.
    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name="Entitlement Corpus",
                provider_config_json=provider_config_json,
            )
        )
        await session.commit()


async def _cleanup_tenant(tenant_id: str) -> None:
    # Keep entitlement tests isolated from shared state.
    async with SessionLocal() as session:
        await session.execute(delete(Corpus).where(Corpus.tenant_id == tenant_id))
        await session.execute(
            delete(TenantFeatureOverride).where(TenantFeatureOverride.tenant_id == tenant_id)
        )
        await session.execute(
            delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id)
        )
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_free_plan_blocks_audio_and_override_allows(monkeypatch) -> None:
    tenant_id = f"t-ent-free-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="free",
    )
    corpus_id = f"c-ent-{uuid4().hex}"
    await _seed_corpus(
        tenant_id,
        corpus_id,
        {"retrieval": {"provider": "local_pgvector", "top_k_default": 5}},
    )

    app = create_app()
    transport = ASGITransport(app=app)
    payload = {
        "session_id": f"s-ent-{uuid4().hex}",
        "corpus_id": corpus_id,
        "message": "Hello?",
        "top_k": 3,
        "audio": True,
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/run", json=payload, headers=headers)
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["code"] == "FEATURE_NOT_ENABLED"
        assert detail["feature_key"] == FEATURE_TTS

        override_payload = {"feature_key": FEATURE_TTS, "enabled": True, "config_json": None}
        response = await client.patch(
            f"/admin/plans/{tenant_id}/overrides",
            json=override_payload,
            headers=headers,
        )
        assert response.status_code == 200

        async with client.stream("POST", "/run", json=payload, headers=headers) as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_provider_gating_blocks_and_allows(monkeypatch) -> None:
    _apply_env(monkeypatch)
    aws_config = {
        "retrieval": {
            "provider": "aws_bedrock_kb",
            "knowledge_base_id": "kb-1",
            "region": "us-east-1",
            "top_k_default": 5,
        }
    }

    free_tenant = f"t-ent-free-{uuid4().hex}"
    _raw_key, free_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=free_tenant,
        role="admin",
        plan_id="free",
    )
    free_corpus = f"c-ent-free-{uuid4().hex}"
    await _seed_corpus(free_tenant, free_corpus, aws_config)

    app = create_app()
    transport = ASGITransport(app=app)
    payload = {
        "session_id": f"s-ent-{uuid4().hex}",
        "corpus_id": free_corpus,
        "message": "Hello?",
        "top_k": 3,
        "audio": False,
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/run", json=payload, headers=free_headers)
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["code"] == "FEATURE_NOT_ENABLED"
        assert detail["feature_key"] == FEATURE_RETRIEVAL_AWS

    await _cleanup_tenant(free_tenant)

    class StubBedrock:
        def __init__(self, knowledge_base_id: str, region: str) -> None:
            self.knowledge_base_id = knowledge_base_id
            self.region = region

        async def retrieve(self, _tenant_id: str, _corpus_id: str, _query: str, _top_k: int):
            return []

    from nexusrag.providers.retrieval import router as retrieval_router

    monkeypatch.setattr(retrieval_router, "BedrockKnowledgeBaseRetriever", StubBedrock)

    enterprise_tenant = f"t-ent-ent-{uuid4().hex}"
    _raw_key, ent_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=enterprise_tenant,
        role="admin",
        plan_id="enterprise",
    )
    enterprise_corpus = f"c-ent-ent-{uuid4().hex}"
    await _seed_corpus(enterprise_tenant, enterprise_corpus, aws_config)

    app = create_app()
    transport = ASGITransport(app=app)
    payload["corpus_id"] = enterprise_corpus

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream("POST", "/run", json=payload, headers=ent_headers) as stream:
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")

    await _cleanup_tenant(enterprise_tenant)


@pytest.mark.asyncio
async def test_ops_and_audit_require_feature_flags(monkeypatch) -> None:
    tenant_id = f"t-ent-free-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="free",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/health", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_NOT_ENABLED"

        response = await client.get("/audit/events", headers=headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_NOT_ENABLED"

    await _cleanup_tenant(tenant_id)


@pytest.mark.asyncio
async def test_admin_plan_assignment_authz_and_scoping(monkeypatch) -> None:
    tenant_id = f"t-ent-admin-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, reader_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )
    _raw_key, admin_headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/admin/plans/{tenant_id}", headers=reader_headers)
        assert response.status_code == 403

        response = await client.get(f"/admin/plans/{tenant_id}", headers=admin_headers)
        assert response.status_code == 200

        response = await client.get("/admin/plans/other-tenant", headers=admin_headers)
        assert response.status_code == 403

        response = await client.patch(
            f"/admin/plans/{tenant_id}",
            json={"plan_id": "pro"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["plan_id"] == "pro"

    await _cleanup_tenant(tenant_id)
