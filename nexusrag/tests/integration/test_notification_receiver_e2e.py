from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from nexusrag.apps.notify_receiver.app import ReceiverSettings, create_app as create_receiver_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    AlertEvent,
    ApiKey,
    AuditEvent,
    AuthorizationPolicy,
    IncidentTimelineEvent,
    NotificationAttempt,
    NotificationDeadLetter,
    NotificationDestination,
    NotificationJob,
    NotificationRoute,
    OpsIncident,
    TenantPlanAssignment,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.operability import notifications as notifications_module
from nexusrag.services.operability.incidents import open_incident_for_alert
from nexusrag.services.operability.notifications import (
    process_notification_job,
    replay_dead_letter,
)
from nexusrag.tests.utils.auth import create_test_api_key


def _utc_now() -> datetime:
    # Keep test-side clock usage in UTC to match production notification timestamp invariants.
    return datetime.now(timezone.utc)


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped rows touched by notification E2E tests for deterministic isolation.
    async with SessionLocal() as session:
        await session.execute(
            delete(NotificationAttempt).where(
                NotificationAttempt.job_id.in_(
                    select(NotificationJob.id).where(NotificationJob.tenant_id == tenant_id)
                )
            )
        )
        await session.execute(delete(NotificationDeadLetter).where(NotificationDeadLetter.tenant_id == tenant_id))
        await session.execute(delete(NotificationRoute).where(NotificationRoute.tenant_id == tenant_id))
        await session.execute(delete(NotificationDestination).where(NotificationDestination.tenant_id == tenant_id))
        await session.execute(delete(NotificationJob).where(NotificationJob.tenant_id == tenant_id))
        await session.execute(delete(AlertEvent).where(AlertEvent.tenant_id == tenant_id))
        await session.execute(delete(IncidentTimelineEvent).where(IncidentTimelineEvent.tenant_id == tenant_id))
        await session.execute(delete(OpsIncident).where(OpsIncident.tenant_id == tenant_id))
        await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        await session.execute(delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id))
        await session.execute(delete(AuthorizationPolicy).where(AuthorizationPolicy.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.commit()


def _receiver_settings(
    *,
    tmp_path: Path,
    require_signature: bool = True,
    shared_secret: str | None = "shared-secret",
    fail_mode: str = "never",
    fail_n: int = 0,
) -> ReceiverSettings:
    # Build per-test receiver settings with isolated sqlite stores to prevent cross-test state bleed.
    db_path = tmp_path / f"receiver-{uuid4().hex}.db"
    return ReceiverSettings(
        shared_secret=shared_secret,
        require_signature=require_signature,
        fail_mode=fail_mode,
        fail_n=fail_n,
        port=9001,
        store_path=str(db_path),
        store_raw_body=False,
    )


def _install_receiver_delivery_adapter(receiver_app) -> None:
    # Route outbound delivery through the reference receiver ASGI app for deterministic sender↔receiver E2E checks.
    async def _deliver_with_receiver(*, destination: str, payload_bytes: bytes, headers: dict[str, str]) -> None:
        parsed = urlparse(destination)
        path = parsed.path or "/webhook"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=receiver_app),
            base_url="http://notify-receiver.local",
        ) as client:
            response = await client.post(path, content=payload_bytes, headers=headers)
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"Receiver rejected notification delivery ({response.status_code})",
                    request=response.request,
                    response=response,
                )

    notifications_module._deliver = _deliver_with_receiver  # type: ignore[assignment]


async def _open_incident_for_notification(tenant_id: str, request_id: str) -> str:
    # Trigger normal incident notification path so job creation uses production routing and dedupe logic.
    async with SessionLocal() as session:
        incident, _created = await open_incident_for_alert(
            session=session,
            tenant_id=tenant_id,
            category="receiver.e2e",
            rule_id=None,
            severity="high",
            title="Receiver e2e incident",
            summary="receiver integration test",
            details_json={"reason": "e2e"},
            actor_id="receiver-e2e",
            actor_role="admin",
            request_id=request_id,
        )
        return incident.id


async def _get_latest_job(tenant_id: str) -> NotificationJob:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(NotificationJob)
                .where(NotificationJob.tenant_id == tenant_id)
                .order_by(NotificationJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        return row


async def _drive_job_to_terminal(job_id: str, *, max_cycles: int = 12) -> NotificationJob:
    # Advance a job through retries without sleeps by forcing retry rows due immediately between attempts.
    for _ in range(max_cycles):
        async with SessionLocal() as session:
            job = await session.get(NotificationJob, job_id)
            assert job is not None
            if job.status in {"delivered", "dlq"}:
                return job
            if job.status == "retrying":
                job.next_attempt_at = _utc_now() - timedelta(seconds=1)
                await session.commit()
            await process_notification_job(session=session, job_id=job_id)
    async with SessionLocal() as session:
        job = await session.get(NotificationJob, job_id)
        assert job is not None
        return job


async def _list_receiver_receipts(receiver_app, *, limit: int = 50) -> list[dict]:
    # Query receiver debug endpoint so assertions validate persisted receipt contract details.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=receiver_app),
        base_url="http://notify-receiver.local",
    ) as client:
        response = await client.get("/received", params={"limit": limit})
        assert response.status_code == 200
        return list(response.json()["items"])


async def _ensure_destination(tenant_id: str, url: str, *, secret: str | None) -> None:
    async with SessionLocal() as session:
        session.add(
            NotificationDestination(
                id=uuid4().hex,
                tenant_id=tenant_id,
                destination_url=url,
                secret_encrypted=notifications_module.encrypt_keyring_secret(secret) if secret else None,
                headers_json={},
                enabled=True,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_notify_e2e_delivered_happy_path(tmp_path: Path, monkeypatch) -> None:
    tenant_id = f"t-notify-e2e-happy-{uuid4().hex}"
    monkeypatch.setenv("KEYRING_MASTER_KEY", "receiver-e2e-key")
    get_settings.cache_clear()
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    receiver_app = create_receiver_app(_receiver_settings(tmp_path=tmp_path, shared_secret="tenant-secret"))
    original_deliver = notifications_module._deliver
    _install_receiver_delivery_adapter(receiver_app)
    try:
        await _ensure_destination(tenant_id, "http://notify_receiver:9001/webhook", secret="tenant-secret")
        await _open_incident_for_notification(tenant_id, "req-happy")
        job = await _get_latest_job(tenant_id)
        final_job = await _drive_job_to_terminal(job.id)
        assert final_job.status == "delivered"
        receipts = await _list_receiver_receipts(receiver_app)
        assert receipts
        latest = receipts[0]
        assert latest["notification_id"] == final_job.id
        assert latest["tenant_id"] == tenant_id
        assert latest["event_type"] == "incident.opened"
        assert latest["signature_present"] == 1
        assert latest["signature_valid"] == 1
    finally:
        notifications_module._deliver = original_deliver  # type: ignore[assignment]
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notify_e2e_retry_then_deliver(tmp_path: Path, monkeypatch) -> None:
    tenant_id = f"t-notify-e2e-retry-{uuid4().hex}"
    monkeypatch.setenv("KEYRING_MASTER_KEY", "receiver-e2e-key")
    get_settings.cache_clear()
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    receiver_app = create_receiver_app(
        _receiver_settings(tmp_path=tmp_path, shared_secret="tenant-secret", fail_mode="first_n", fail_n=2)
    )
    original_deliver = notifications_module._deliver
    _install_receiver_delivery_adapter(receiver_app)
    try:
        await _ensure_destination(tenant_id, "http://notify_receiver:9001/webhook", secret="tenant-secret")
        await _open_incident_for_notification(tenant_id, "req-retry")
        job = await _get_latest_job(tenant_id)
        final_job = await _drive_job_to_terminal(job.id, max_cycles=16)
        assert final_job.status == "delivered"
        assert final_job.attempt_count >= 3
    finally:
        notifications_module._deliver = original_deliver  # type: ignore[assignment]
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notify_e2e_invalid_signature_rejected(tmp_path: Path, monkeypatch) -> None:
    tenant_id = f"t-notify-e2e-sig-mismatch-{uuid4().hex}"
    monkeypatch.setenv("KEYRING_MASTER_KEY", "receiver-e2e-key")
    get_settings.cache_clear()
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    receiver_app = create_receiver_app(_receiver_settings(tmp_path=tmp_path, shared_secret="receiver-secret"))
    original_deliver = notifications_module._deliver
    _install_receiver_delivery_adapter(receiver_app)
    try:
        await _ensure_destination(tenant_id, "http://notify_receiver:9001/webhook", secret="sender-secret")
        await _open_incident_for_notification(tenant_id, "req-bad-signature")
        job = await _get_latest_job(tenant_id)
        final_job = await _drive_job_to_terminal(job.id)
        assert final_job.status == "dlq"
        async with SessionLocal() as session:
            dead_letter = (
                await session.execute(
                    select(NotificationDeadLetter).where(NotificationDeadLetter.job_id == final_job.id)
                )
            ).scalar_one()
            assert dead_letter.reason == "receiver_rejected"
    finally:
        notifications_module._deliver = original_deliver  # type: ignore[assignment]
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notify_e2e_missing_signature_rejected_when_required(tmp_path: Path, monkeypatch) -> None:
    tenant_id = f"t-notify-e2e-missing-signature-{uuid4().hex}"
    monkeypatch.setenv("KEYRING_MASTER_KEY", "receiver-e2e-key")
    get_settings.cache_clear()
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    receiver_app = create_receiver_app(_receiver_settings(tmp_path=tmp_path, shared_secret="receiver-secret"))
    original_deliver = notifications_module._deliver
    _install_receiver_delivery_adapter(receiver_app)
    try:
        # Leave sender destination secret unset so signature header is omitted while receiver requires signatures.
        await _ensure_destination(tenant_id, "http://notify_receiver:9001/webhook", secret=None)
        await _open_incident_for_notification(tenant_id, "req-missing-signature")
        job = await _get_latest_job(tenant_id)
        final_job = await _drive_job_to_terminal(job.id)
        assert final_job.status == "dlq"
        async with SessionLocal() as session:
            dead_letter = (
                await session.execute(
                    select(NotificationDeadLetter).where(NotificationDeadLetter.job_id == final_job.id)
                )
            ).scalar_one()
            assert dead_letter.reason == "receiver_rejected"
    finally:
        notifications_module._deliver = original_deliver  # type: ignore[assignment]
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notify_e2e_max_age_expired_to_dlq(tmp_path: Path, monkeypatch) -> None:
    tenant_id = f"t-notify-e2e-expired-{uuid4().hex}"
    monkeypatch.setenv("KEYRING_MASTER_KEY", "receiver-e2e-key")
    monkeypatch.setenv("NOTIFY_MAX_AGE_SECONDS", "1")
    get_settings.cache_clear()
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    receiver_app = create_receiver_app(_receiver_settings(tmp_path=tmp_path, shared_secret="tenant-secret"))
    original_deliver = notifications_module._deliver
    _install_receiver_delivery_adapter(receiver_app)
    try:
        old_created_at = _utc_now() - timedelta(hours=2)
        async with SessionLocal() as session:
            session.add(
                NotificationJob(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    incident_id=None,
                    alert_event_id=None,
                    destination="http://notify_receiver:9001/webhook",
                    dedupe_key="expired-test",
                    dedupe_window_start=old_created_at,
                    payload_json={"event_type": "incident.opened", "tenant_id": tenant_id, "payload": {}},
                    status="queued",
                    next_attempt_at=old_created_at,
                    attempt_count=0,
                    last_error=None,
                    created_at=old_created_at,
                    updated_at=old_created_at,
                )
            )
            await session.commit()
            job = (
                await session.execute(
                    select(NotificationJob).where(NotificationJob.tenant_id == tenant_id).limit(1)
                )
            ).scalar_one()
            final_job = await _drive_job_to_terminal(job.id)
            assert final_job.status == "dlq"
            dead_letter = (
                await session.execute(
                    select(NotificationDeadLetter).where(NotificationDeadLetter.job_id == job.id)
                )
            ).scalar_one()
            assert dead_letter.reason == "expired"
    finally:
        notifications_module._deliver = original_deliver  # type: ignore[assignment]
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notify_e2e_dlq_replay_new_id(tmp_path: Path, monkeypatch) -> None:
    tenant_id = f"t-notify-e2e-replay-{uuid4().hex}"
    monkeypatch.setenv("KEYRING_MASTER_KEY", "receiver-e2e-key")
    monkeypatch.setenv("NOTIFY_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    failing_receiver = create_receiver_app(
        _receiver_settings(tmp_path=tmp_path, shared_secret="tenant-secret", fail_mode="always")
    )
    original_deliver = notifications_module._deliver
    _install_receiver_delivery_adapter(failing_receiver)
    try:
        await _ensure_destination(tenant_id, "http://notify_receiver:9001/webhook", secret="tenant-secret")
        await _open_incident_for_notification(tenant_id, "req-replay")
        job = await _get_latest_job(tenant_id)
        failed_job = await _drive_job_to_terminal(job.id, max_cycles=8)
        assert failed_job.status == "dlq"
        async with SessionLocal() as session:
            dead_letter = (
                await session.execute(
                    select(NotificationDeadLetter).where(NotificationDeadLetter.job_id == failed_job.id)
                )
            ).scalar_one()

        success_receiver = create_receiver_app(_receiver_settings(tmp_path=tmp_path, shared_secret="tenant-secret"))
        _install_receiver_delivery_adapter(success_receiver)
        async with SessionLocal() as session:
            replay_payload = await replay_dead_letter(
                session=session,
                tenant_id=tenant_id,
                dead_letter_id=dead_letter.id,
                actor_id="receiver-e2e",
                actor_role="admin",
                request_id="req-replay-run",
            )
            assert replay_payload is not None
            created_job_ids = replay_payload["created_job_ids"]
            assert created_job_ids
            replay_job_id = created_job_ids[0]
            assert replay_job_id != failed_job.id
        replay_job = await _drive_job_to_terminal(replay_job_id, max_cycles=8)
        assert replay_job.status == "delivered"
        receipts = await _list_receiver_receipts(success_receiver, limit=100)
        ids = {row["notification_id"] for row in receipts}
        assert replay_job_id in ids
        assert failed_job.id not in ids
    finally:
        notifications_module._deliver = original_deliver  # type: ignore[assignment]
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notify_e2e_tenant_scoping_preserved_in_receiver_headers(tmp_path: Path, monkeypatch) -> None:
    tenant_a = f"t-notify-e2e-tenant-a-{uuid4().hex}"
    tenant_b = f"t-notify-e2e-tenant-b-{uuid4().hex}"
    monkeypatch.setenv("KEYRING_MASTER_KEY", "receiver-e2e-key")
    get_settings.cache_clear()
    await create_test_api_key(tenant_id=tenant_a, role="admin", plan_id="enterprise")
    await create_test_api_key(tenant_id=tenant_b, role="admin", plan_id="enterprise")
    receiver_app = create_receiver_app(_receiver_settings(tmp_path=tmp_path, shared_secret="tenant-secret"))
    original_deliver = notifications_module._deliver
    _install_receiver_delivery_adapter(receiver_app)
    try:
        await _ensure_destination(tenant_a, "http://notify_receiver:9001/webhook", secret="tenant-secret")
        await _ensure_destination(tenant_b, "http://notify_receiver:9001/webhook", secret="tenant-secret")
        await _open_incident_for_notification(tenant_a, "req-tenant-a")
        await _open_incident_for_notification(tenant_b, "req-tenant-b")
        job_a = await _get_latest_job(tenant_a)
        job_b = await _get_latest_job(tenant_b)
        final_a = await _drive_job_to_terminal(job_a.id)
        final_b = await _drive_job_to_terminal(job_b.id)
        assert final_a.status == "delivered"
        assert final_b.status == "delivered"
        receipts = await _list_receiver_receipts(receiver_app, limit=100)
        by_id = {row["notification_id"]: row for row in receipts}
        assert by_id[final_a.id]["tenant_id"] == tenant_a
        assert by_id[final_b.id]["tenant_id"] == tenant_b
    finally:
        notifications_module._deliver = original_deliver  # type: ignore[assignment]
        await _cleanup_tenant(tenant_a)
        await _cleanup_tenant(tenant_b)
        get_settings.cache_clear()
