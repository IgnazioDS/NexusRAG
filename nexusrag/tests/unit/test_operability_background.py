from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    AlertEvent,
    ApiKey,
    AuditEvent,
    IncidentTimelineEvent,
    NotificationAttempt,
    NotificationDestination,
    NotificationJob,
    OpsIncident,
    TenantPlanAssignment,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.operability import actions as actions_module
from nexusrag.services.operability import notifications as notifications_module
from nexusrag.services.operability import worker as worker_module
from nexusrag.services.operability.notifications import (
    dedupe_window_start,
    retry_backoff_ms,
    send_operability_notification,
)
from nexusrag.services.operability.worker import acquire_evaluator_lock, release_evaluator_lock
from nexusrag.tests.utils.auth import create_test_api_key


class _FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, tuple[str, int | None]] = {}
        self._counters: dict[str, int] = {}
        self.now = 0

    def advance(self, seconds: int) -> None:
        self.now += int(seconds)

    def _expired(self, key: str) -> bool:
        item = self._values.get(key)
        if item is None:
            return True
        _value, expiry = item
        return expiry is not None and self.now >= expiry

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):  # noqa: ANN001
        if nx and not self._expired(key):
            return False
        expiry = self.now + int(ex) if ex is not None else None
        self._values[key] = (str(value), expiry)
        return True

    async def get(self, key: str):  # noqa: ANN001
        if self._expired(key):
            self._values.pop(key, None)
            return None
        return self._values[key][0]

    async def delete(self, key: str) -> int:
        existed = key in self._values
        self._values.pop(key, None)
        return 1 if existed else 0

    async def incr(self, key: str) -> int:
        current = int(self._counters.get(key, 0)) + 1
        self._counters[key] = current
        return current


async def _cleanup_tenant(tenant_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(NotificationAttempt).where(
                NotificationAttempt.job_id.in_(select(NotificationJob.id).where(NotificationJob.tenant_id == tenant_id))
            )
        )
        await session.execute(delete(NotificationDestination).where(NotificationDestination.tenant_id == tenant_id))
        await session.execute(delete(NotificationJob).where(NotificationJob.tenant_id == tenant_id))
        await session.execute(delete(AlertEvent).where(AlertEvent.tenant_id == tenant_id))
        await session.execute(delete(IncidentTimelineEvent).where(IncidentTimelineEvent.tenant_id == tenant_id))
        await session.execute(delete(OpsIncident).where(OpsIncident.tenant_id == tenant_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.execute(delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_retry_backoff_and_dedupe_window_are_deterministic() -> None:
    base = retry_backoff_ms(job_id="job-1", attempt_no=2)
    assert base == retry_backoff_ms(job_id="job-1", attempt_no=2)
    assert base > 0
    rounded = dedupe_window_start(
        now=datetime(2026, 2, 18, 12, 7, 59, tzinfo=timezone.utc),
        window_seconds=300,
    )
    assert rounded.isoformat() == "2026-02-18T12:05:00+00:00"


@pytest.mark.asyncio
async def test_distributed_lock_single_owner(monkeypatch) -> None:
    redis = _FakeRedis()

    async def _redis():  # type: ignore[override]
        return redis

    monkeypatch.setattr(worker_module, "get_resilience_redis", _redis)
    lock_one = await acquire_evaluator_lock()
    lock_two = await acquire_evaluator_lock()
    assert lock_one is not None
    assert lock_two is None
    await release_evaluator_lock(lock_one)
    lock_three = await acquire_evaluator_lock()
    assert lock_three is not None
    await release_evaluator_lock(lock_three)


@pytest.mark.asyncio
async def test_forced_flags_ttl_region_and_fail_open(monkeypatch) -> None:
    redis = _FakeRedis()

    async def _redis():  # type: ignore[override]
        return redis

    monkeypatch.setattr(actions_module, "get_resilience_redis", _redis)
    monkeypatch.setenv("REGION_ROLE", "primary")
    monkeypatch.setenv("FAILOVER_MODE", "manual")
    monkeypatch.setenv("REGION_ID", "ap-southeast-1")
    get_settings.cache_clear()
    applied = await actions_module.set_forced_shed(tenant_id="t-ops", route_class="run", enabled=True, ttl_s=2)
    assert applied["applied"] is True
    assert await actions_module.get_forced_shed(tenant_id="t-ops", route_class="run") is True
    redis.advance(3)
    assert await actions_module.get_forced_shed(tenant_id="t-ops", route_class="run") is False

    lease_block_redis = _FakeRedis()
    await lease_block_redis.set("forced_control_writer_lease:ap-southeast-1", "other-region:token", ex=30)

    async def _lease_blocked_redis():  # type: ignore[override]
        return lease_block_redis

    monkeypatch.setattr(actions_module, "get_resilience_redis", _lease_blocked_redis)
    lease_blocked = await actions_module.set_forced_tts_disabled(tenant_id="t-ops", disabled=True)
    assert lease_blocked["applied"] is False
    assert lease_blocked["reason"] == "writer_lease_unavailable"

    monkeypatch.setenv("REGION_ROLE", "standby")
    monkeypatch.setenv("FAILOVER_MODE", "manual")
    get_settings.cache_clear()
    blocked = await actions_module.set_forced_tts_disabled(tenant_id="t-ops", disabled=True)
    assert blocked["applied"] is False
    assert blocked["reason"] == "region_not_allowed"

    async def _no_redis():  # type: ignore[override]
        return None

    monkeypatch.setattr(actions_module, "get_resilience_redis", _no_redis)
    fail_open = await actions_module.set_forced_tts_disabled(tenant_id="t-ops", disabled=True)
    assert fail_open["applied"] is False
    assert fail_open["reason"] == "redis_unavailable"
    assert await actions_module.get_forced_tts_disabled(tenant_id="t-ops") is False


@pytest.mark.asyncio
async def test_notification_enqueue_dedupes_within_window(monkeypatch) -> None:
    tenant_id = f"t-notify-dedupe-{uuid4().hex}"
    monkeypatch.setenv("NOTIFY_WEBHOOK_URLS_JSON", "[\"noop://local\"]")
    get_settings.cache_clear()
    fixed_now = datetime(2026, 2, 18, 12, 8, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(notifications_module, "_utc_now", lambda: fixed_now)
    monkeypatch.setattr(notifications_module, "_global_notification_destinations", lambda: ["noop://local"])

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    try:
        async with SessionLocal() as session:
            incident_id = f"inc-{uuid4().hex}"
            session.add(
                OpsIncident(
                    id=incident_id,
                    tenant_id=tenant_id,
                    category="test",
                    rule_id=None,
                    severity="high",
                    status="open",
                    title="test",
                    summary="test",
                    dedupe_key=f"{tenant_id}:test:none",
                    opened_at=fixed_now,
                    details_json={},
                )
            )
            await session.commit()
            payload = {"incident_id": incident_id, "severity": "high"}
            await send_operability_notification(
                session=session,
                tenant_id=tenant_id,
                event_type="incident.opened",
                payload=payload,
                actor_id="tester",
                actor_role="admin",
                request_id="req-1",
            )
            await send_operability_notification(
                session=session,
                tenant_id=tenant_id,
                event_type="incident.opened",
                payload=payload,
                actor_id="tester",
                actor_role="admin",
                request_id="req-2",
            )
            jobs = (
                await session.execute(select(NotificationJob).where(NotificationJob.tenant_id == tenant_id))
            ).scalars().all()
            assert len(jobs) == 1
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_destination_resolution_prefers_tenant_rows(monkeypatch) -> None:
    tenant_id = f"t-notify-dest-{uuid4().hex}"
    other_tenant_id = f"{tenant_id}-other"
    monkeypatch.setenv("NOTIFY_WEBHOOK_URLS_JSON", "[\"noop://global-default\"]")
    get_settings.cache_clear()
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    try:
        async with SessionLocal() as session:
            session.add(
                NotificationDestination(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    destination_url="noop://tenant-destination",
                    enabled=True,
                )
            )
            await session.commit()
            tenant_destinations = await notifications_module.resolve_notification_destinations(
                session=session,
                tenant_id=tenant_id,
            )
            global_destinations = await notifications_module.resolve_notification_destinations(
                session=session,
                tenant_id=other_tenant_id,
            )
            assert tenant_destinations == ["noop://tenant-destination"]
            assert global_destinations == ["noop://global-default"]
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_tenant(other_tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_job_cas_prevents_reprocessing(monkeypatch) -> None:
    tenant_id = f"t-notify-cas-{uuid4().hex}"
    fixed_now = datetime(2026, 2, 18, 12, 8, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(notifications_module, "_utc_now", lambda: fixed_now)

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    job_id = uuid4().hex
    try:
        async with SessionLocal() as session:
            session.add(
                NotificationJob(
                    id=job_id,
                    tenant_id=tenant_id,
                    incident_id=None,
                    alert_event_id=None,
                    destination="noop://cas",
                    dedupe_key="incident.opened",
                    dedupe_window_start=fixed_now,
                    payload_json={"event_type": "incident.opened"},
                    status="queued",
                    next_attempt_at=fixed_now,
                    attempt_count=0,
                    last_error=None,
                )
            )
            await session.commit()

        async with SessionLocal() as session:
            processed = await notifications_module.process_notification_job(session=session, job_id=job_id)
            assert processed is not None
            assert processed.status == "succeeded"

        async with SessionLocal() as session:
            second = await notifications_module.process_notification_job(session=session, job_id=job_id)
            assert second is None
    finally:
        await _cleanup_tenant(tenant_id)
