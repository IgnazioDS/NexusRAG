from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import FailoverClusterState, FailoverEvent, FailoverToken, RegionStatus
from nexusrag.persistence.db import SessionLocal
from nexusrag.services import failover as failover_service
from nexusrag.tests.utils.auth import create_test_api_key


async def _reset_failover_rows() -> None:
    # Keep integration assertions deterministic by resetting failover tables.
    async with SessionLocal() as session:
        await session.execute(delete(FailoverEvent))
        await session.execute(delete(FailoverToken))
        await session.execute(delete(FailoverClusterState))
        await session.execute(delete(RegionStatus))
        await session.commit()


def _build_client() -> tuple[ASGITransport, object]:
    get_settings.cache_clear()
    app = create_app()
    return ASGITransport(app=app), app


@pytest.mark.asyncio
async def test_non_admin_forbidden_on_failover_endpoints() -> None:
    await _reset_failover_rows()
    transport, _app = _build_client()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t-fo-1", role="reader")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/ops/failover/status", headers=headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_invalid_and_expired_token_rejected(monkeypatch) -> None:
    await _reset_failover_rows()
    monkeypatch.setenv("FAILOVER_COOLDOWN_SECONDS", "0")
    transport, _app = _build_client()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t-fo-2", role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/ops/failover/promote",
            headers=headers,
            json={
                "target_region": get_settings().region_id,
                "token": "invalid-token",
                "reason": "unit-test",
                "force": False,
            },
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "FAILOVER_TOKEN_INVALID"

        token_resp = await client.post(
            "/v1/ops/failover/request-token",
            headers=headers,
            json={"purpose": "promote", "reason": "expire"},
        )
        assert token_resp.status_code == 200
        token = token_resp.json()["data"]["token"]

    async with SessionLocal() as session:
        token_row = (
            await session.execute(
                select(FailoverToken).where(FailoverToken.token_hash == failover_service.token_hash(token))
            )
        ).scalar_one()
        token_row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        expired = await client.post(
            "/v1/ops/failover/promote",
            headers=headers,
            json={
                "target_region": get_settings().region_id,
                "token": token,
                "reason": "expired",
                "force": False,
            },
        )
        assert expired.status_code == 401
        assert expired.json()["error"]["code"] == "FAILOVER_TOKEN_INVALID"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_successful_promote_updates_primary_and_epoch(monkeypatch) -> None:
    await _reset_failover_rows()
    monkeypatch.setenv("FAILOVER_COOLDOWN_SECONDS", "0")
    transport, _app = _build_client()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t-fo-3", role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token_resp = await client.post(
            "/v1/ops/failover/request-token",
            headers=headers,
            json={"purpose": "promote", "reason": "promote"},
        )
        token = token_resp.json()["data"]["token"]
        promote_resp = await client.post(
            "/v1/ops/failover/promote",
            headers=headers,
            json={
                "target_region": get_settings().region_id,
                "token": token,
                "reason": "promote",
                "force": False,
            },
        )
        assert promote_resp.status_code == 200
        payload = promote_resp.json()["data"]
        assert payload["status"] == "completed"
        status_resp = await client.get("/v1/ops/failover/status", headers=headers)
        assert status_resp.status_code == 200
        status_payload = status_resp.json()["data"]
        assert status_payload["active_primary_region"] == get_settings().region_id
        assert status_payload["epoch"] >= 2
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_concurrent_promote_one_rejected_in_progress(monkeypatch) -> None:
    await _reset_failover_rows()
    monkeypatch.setenv("FAILOVER_COOLDOWN_SECONDS", "0")
    transport, _app = _build_client()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t-fo-4", role="admin")

    original_eval = failover_service.evaluate_readiness

    async def slow_evaluate(session, *args, **kwargs):
        await asyncio.sleep(0.2)
        return await original_eval(session, *args, **kwargs)

    monkeypatch.setattr(failover_service, "evaluate_readiness", slow_evaluate)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token_a = (
            await client.post(
                "/v1/ops/failover/request-token",
                headers=headers,
                json={"purpose": "promote", "reason": "concurrent-a"},
            )
        ).json()["data"]["token"]
        token_b = (
            await client.post(
                "/v1/ops/failover/request-token",
                headers=headers,
                json={"purpose": "promote", "reason": "concurrent-b"},
            )
        ).json()["data"]["token"]

        async def _promote(token: str):
            return await client.post(
                "/v1/ops/failover/promote",
                headers=headers,
                json={
                    "target_region": get_settings().region_id,
                    "token": token,
                    "reason": "concurrent",
                    "force": False,
                },
            )

        resp_a, resp_b = await asyncio.gather(_promote(token_a), _promote(token_b))

    statuses = sorted([resp_a.status_code, resp_b.status_code])
    assert statuses == [200, 409]
    failed_resp = resp_a if resp_a.status_code == 409 else resp_b
    assert failed_resp.json()["error"]["code"] == "FAILOVER_IN_PROGRESS"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_write_freeze_blocks_mutation() -> None:
    await _reset_failover_rows()
    transport, _app = _build_client()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t-fo-5", role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        freeze_resp = await client.patch(
            "/v1/ops/failover/freeze-writes",
            headers=headers,
            json={"freeze": True, "reason": "maintenance"},
        )
        assert freeze_resp.status_code == 200

        blocked = await client.post(
            "/v1/documents/text",
            headers=headers,
            json={"corpus_id": "c1", "text": "hello"},
        )
        assert blocked.status_code == 503
        assert blocked.json()["error"]["code"] == "WRITE_FROZEN"

        unfreeze = await client.patch(
            "/v1/ops/failover/freeze-writes",
            headers=headers,
            json={"freeze": False, "reason": "done"},
        )
        assert unfreeze.status_code == 200


@pytest.mark.asyncio
async def test_readiness_split_brain_and_promote_denied(monkeypatch) -> None:
    await _reset_failover_rows()
    monkeypatch.setenv(
        "PEER_REGIONS_JSON",
        '[{"id":"us-east-1","health_status":"healthy","active_primary_region":"us-east-1","role":"primary"}]',
    )
    monkeypatch.setenv("FAILOVER_COOLDOWN_SECONDS", "0")
    transport, _app = _build_client()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t-fo-6", role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        readiness = await client.get("/v1/ops/failover/readiness", headers=headers)
        assert readiness.status_code == 200
        payload = readiness.json()["data"]
        assert payload["split_brain_risk"] is True
        assert "SPLIT_BRAIN_RISK" in payload["blockers"]

        token_resp = await client.post(
            "/v1/ops/failover/request-token",
            headers=headers,
            json={"purpose": "promote", "reason": "split-brain-check"},
        )
        token = token_resp.json()["data"]["token"]
        promote = await client.post(
            "/v1/ops/failover/promote",
            headers=headers,
            json={
                "target_region": get_settings().region_id,
                "token": token,
                "reason": "split-brain-check",
                "force": False,
            },
        )
        assert promote.status_code == 409
        assert promote.json()["error"]["code"] == "SPLIT_BRAIN_RISK"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rollback_requires_token_and_updates_state(monkeypatch) -> None:
    await _reset_failover_rows()
    monkeypatch.setenv("FAILOVER_COOLDOWN_SECONDS", "0")
    transport, _app = _build_client()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t-fo-7", role="admin")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        promote_token = (
            await client.post(
                "/v1/ops/failover/request-token",
                headers=headers,
                json={"purpose": "promote", "reason": "before-rollback"},
            )
        ).json()["data"]["token"]
        promote_resp = await client.post(
            "/v1/ops/failover/promote",
            headers=headers,
            json={
                "target_region": get_settings().region_id,
                "token": promote_token,
                "reason": "before-rollback",
                "force": False,
            },
        )
        assert promote_resp.status_code == 200

        invalid = await client.post(
            "/v1/ops/failover/rollback",
            headers=headers,
            json={"token": "invalid", "reason": "rollback-invalid"},
        )
        assert invalid.status_code == 401
        assert invalid.json()["error"]["code"] == "FAILOVER_TOKEN_INVALID"

        rollback_token = (
            await client.post(
                "/v1/ops/failover/request-token",
                headers=headers,
                json={"purpose": "rollback", "reason": "rollback"},
            )
        ).json()["data"]["token"]
        rollback_resp = await client.post(
            "/v1/ops/failover/rollback",
            headers=headers,
            json={"token": rollback_token, "reason": "rollback"},
        )
        assert rollback_resp.status_code == 200
        assert rollback_resp.json()["data"]["status"] == "rolled_back"
    get_settings.cache_clear()
