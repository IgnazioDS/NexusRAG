from __future__ import annotations

from datetime import timedelta, timezone, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from nexusrag.core.config import get_settings
from nexusrag.domain.models import FailoverClusterState, FailoverToken, RegionStatus
from nexusrag.persistence.db import SessionLocal
from nexusrag.services import failover


async def _reset_failover_rows() -> None:
    # Keep unit tests deterministic by clearing failover state before assertions.
    async with SessionLocal() as session:
        await session.execute(delete(FailoverToken))
        await session.execute(delete(FailoverClusterState))
        await session.execute(delete(RegionStatus))
        await session.commit()


def test_state_transition_rules() -> None:
    # Validate state machine transitions for promote/rollback workflows.
    assert failover._state_transition_allowed("idle", "precheck")
    assert failover._state_transition_allowed("precheck", "promoting")
    assert failover._state_transition_allowed("verification", "completed")
    assert not failover._state_transition_allowed("idle", "completed")
    assert not failover._state_transition_allowed("failed", "promoting")


def test_token_hash_is_stable() -> None:
    # Ensure token hashing is deterministic and plaintext-independent per hash.
    value = "token-value"
    assert failover.token_hash(value) == failover.token_hash(value)
    assert failover.token_hash(value) != failover.token_hash("different-token")


@pytest.mark.asyncio
async def test_token_consumption_one_time_and_expiry() -> None:
    # Enforce one-time token semantics and expiry checks.
    await _reset_failover_rows()
    get_settings.cache_clear()
    async with SessionLocal() as session:
        issued = await failover.issue_failover_token(
            session=session,
            requested_by_actor_id="actor1",
            purpose=failover.TOKEN_PURPOSE_PROMOTE,
            reason="unit-test",
            tenant_id="t1",
            actor_role="admin",
            request_id="req-1",
        )
        token = await failover._consume_token(
            session,
            plaintext=issued.token,
            purpose=failover.TOKEN_PURPOSE_PROMOTE,
        )
        assert token.id == issued.token_id
        with pytest.raises(HTTPException) as exc_info:
            await failover._consume_token(
                session,
                plaintext=issued.token,
                purpose=failover.TOKEN_PURPOSE_PROMOTE,
            )
        assert exc_info.value.detail["code"] == "FAILOVER_TOKEN_INVALID"

        expired_plaintext = "expired-token"
        session.add(
            FailoverToken(
                id="expired",
                token_hash=failover.token_hash(expired_plaintext),
                requested_by_actor_id="actor2",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                used_at=None,
                purpose=failover.TOKEN_PURPOSE_PROMOTE,
            )
        )
        await session.commit()
        with pytest.raises(HTTPException) as expired_exc:
            await failover._consume_token(
                session,
                plaintext=expired_plaintext,
                purpose=failover.TOKEN_PURPOSE_PROMOTE,
            )
        assert expired_exc.value.detail["code"] == "FAILOVER_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_readiness_blockers_include_lag_and_split_brain(monkeypatch) -> None:
    # Fail readiness when lag exceeds threshold and peer signals split-brain.
    await _reset_failover_rows()
    monkeypatch.setenv("REPLICATION_LAG_MAX_SECONDS", "1")
    monkeypatch.setenv(
        "PEER_REGIONS_JSON",
        '[{"id":"us-east-1","health_status":"healthy","active_primary_region":"us-east-1","role":"primary"}]',
    )
    get_settings.cache_clear()
    settings = get_settings()

    async with SessionLocal() as session:
        session.add(
            RegionStatus(
                region_id=settings.region_id,
                role="primary",
                health_status="healthy",
                replication_lag_seconds=10,
                last_heartbeat_at=datetime.now(timezone.utc),
                writable=True,
                metadata_json={},
            )
        )
        session.add(
            FailoverClusterState(
                id=1,
                active_primary_region="us-east-1",
                epoch=5,
                last_transition_at=datetime.now(timezone.utc),
                cooldown_until=None,
                freeze_writes=False,
                metadata_json={"state": "idle"},
            )
        )
        await session.commit()

    async with SessionLocal() as session:
        readiness = await failover.evaluate_readiness(session)
    assert "REPLICATION_LAG_TOO_HIGH" in readiness.blockers
    assert "SPLIT_BRAIN_RISK" in readiness.blockers
    assert readiness.split_brain_risk is True
    get_settings.cache_clear()
