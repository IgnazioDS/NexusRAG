from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from nexusrag.apps.api import rate_limit
from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    AlertEvent,
    AlertRule,
    ApiKey,
    AuditEvent,
    AuthorizationPolicy,
    IdempotencyRecord,
    IncidentTimelineEvent,
    NotificationAttempt,
    NotificationDeadLetter,
    NotificationDestination,
    NotificationJob,
    NotificationRoute,
    OperatorAction,
    OpsIncident,
    TenantPlanAssignment,
    User,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.entitlements import reset_entitlements_cache
from nexusrag.services.operability.notifications import process_notification_job
from nexusrag.services.operability.worker import run_background_evaluator_cycle
from nexusrag.services.resilience import get_resilience_redis
from nexusrag.tests.utils.auth import create_test_api_key


def _apply_env(monkeypatch) -> None:
    # Keep operability integration tests deterministic with fake providers and permissive limits.
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("ALERTING_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("OPS_NOTIFICATION_ADAPTER", "noop")
    monkeypatch.setenv("KEYRING_MASTER_KEY", "local-test-key")
    monkeypatch.setenv("FAILOVER_ENABLED", "false")
    monkeypatch.setenv("RL_KEY_READ_RPS", "100")
    monkeypatch.setenv("RL_KEY_READ_BURST", "200")
    monkeypatch.setenv("RL_TENANT_READ_RPS", "100")
    monkeypatch.setenv("RL_TENANT_READ_BURST", "200")
    monkeypatch.setenv("RL_KEY_MUTATION_RPS", "100")
    monkeypatch.setenv("RL_KEY_MUTATION_BURST", "200")
    monkeypatch.setenv("RL_TENANT_MUTATION_RPS", "100")
    monkeypatch.setenv("RL_TENANT_MUTATION_BURST", "200")
    get_settings.cache_clear()
    rate_limit.reset_rate_limiter_state()
    reset_entitlements_cache()


async def _cleanup_tenant(tenant_id: str) -> None:
    # Remove tenant-scoped rows touched by operability APIs for deterministic isolation.
    async with SessionLocal() as session:
        for _ in range(3):
            try:
                # Retry cleanup because worker threads can append attempts while teardown is running.
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
                await session.execute(delete(OperatorAction).where(OperatorAction.tenant_id == tenant_id))
                await session.execute(delete(AlertRule).where(AlertRule.tenant_id == tenant_id))
                await session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.tenant_id == tenant_id))
                await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
                await session.execute(delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id))
                await session.execute(delete(AuthorizationPolicy).where(AuthorizationPolicy.tenant_id == tenant_id))
                await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
                await session.execute(delete(User).where(User.tenant_id == tenant_id))
                await session.commit()
                break
            except IntegrityError:
                await session.rollback()
        else:
            raise RuntimeError("operability cleanup retries exhausted for notification teardown")


@pytest.mark.asyncio
async def test_alert_evaluate_triggers_and_dedupes_incidents(monkeypatch) -> None:
    tenant_id = f"t-operability-alert-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    async def _metrics_stub(*, session, tenant_id, window):  # type: ignore[override]
        return {
            "slo.burn_rate": 3.0,
            "error.rate": 0.25,
            "latency.p95.run": 6000.0,
            "latency.p99.run": 8000.0,
            "queue.depth": 200,
            "worker.heartbeat.age_s": 200,
            "breaker.open.count": 2,
            "sla.breach.streak": 3,
            "sla.shed.count": 2,
            "quota.hard_cap.blocks": 1,
            "rate_limit.hit.spike": 150,
        }

    from nexusrag.services.operability import alerts as alerts_module

    monkeypatch.setattr(alerts_module, "_collect_metrics", _metrics_stub)

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/v1/admin/alerts/evaluate?window=5m", headers=headers)
            assert first.status_code == 200
            first_payload = first.json()["data"]
            assert first_payload["triggered_alerts"]

            second = await client.post("/v1/admin/alerts/evaluate?window=5m", headers=headers)
            assert second.status_code == 200

        async with SessionLocal() as session:
            incidents = (
                await session.execute(
                    select(OpsIncident).where(
                        OpsIncident.tenant_id == tenant_id,
                        OpsIncident.category == "slo.burn_rate",
                        OpsIncident.status != "resolved",
                    )
                )
            ).scalars().all()
            assert len(incidents) == 1
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_incident_endpoints_require_admin(monkeypatch) -> None:
    tenant_id = f"t-operability-rbac-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/admin/incidents", headers=headers)
            assert response.status_code == 403
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ops_actions_are_idempotent_and_audited(monkeypatch) -> None:
    tenant_id = f"t-operability-action-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    headers_with_idem = {**headers, "Idempotency-Key": "idem-ops-action-1"}
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/v1/admin/ops/actions/disable-tts", headers=headers_with_idem)
            assert first.status_code == 200
            second = await client.post("/v1/admin/ops/actions/disable-tts", headers=headers_with_idem)
            assert second.status_code == 200
            assert second.headers.get("Idempotency-Replayed") == "true"
        async with SessionLocal() as session:
            action_count = await session.scalar(
                select(func.count()).select_from(OperatorAction).where(OperatorAction.tenant_id == tenant_id)
            )
            assert int(action_count or 0) == 1
            audit_rows = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.event_type == "ops.action.disable_tts",
                    )
                )
            ).scalars().all()
            assert audit_rows
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_preflight_script_passes(monkeypatch, tmp_path: Path) -> None:
    _apply_env(monkeypatch)
    settings = get_settings()
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("REDIS_URL", settings.redis_url)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("SLA_ENGINE_ENABLED", "true")
    from scripts.preflight import run_preflight

    rc = await run_preflight(output_json=str(tmp_path / "preflight.json"))
    assert rc == 0


@pytest.mark.asyncio
async def test_background_evaluator_opens_incidents_without_request_traffic(monkeypatch) -> None:
    tenant_id = f"t-operability-worker-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, _headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    async def _metrics_stub(*, session, tenant_id, window):  # type: ignore[override]
        return {
            "slo.burn_rate": 4.0,
            "error.rate": 0.25,
            "latency.p95.run": 7000.0,
            "latency.p99.run": 9000.0,
            "queue.depth": 250,
            "worker.heartbeat.age_s": 300,
            "breaker.open.count": 2,
            "sla.breach.streak": 2,
            "sla.shed.count": 2,
            "quota.hard_cap.blocks": 2,
            "rate_limit.hit.spike": 200,
        }

    from nexusrag.services.operability import alerts as alerts_module
    from nexusrag.services.operability import worker as worker_module

    monkeypatch.setattr(alerts_module, "_collect_metrics", _metrics_stub)
    # Keep evaluator test bounded to this tenant so fixture residue never amplifies test runtime.
    async def _tenant_ids_stub(session):  # type: ignore[override]
        _ = session
        return [tenant_id]

    monkeypatch.setattr(worker_module, "list_alerting_tenant_ids", _tenant_ids_stub)
    try:
        redis = await get_resilience_redis()
        if redis is not None:
            await redis.delete("nexusrag:ops:evaluator:lock")
        result = await run_background_evaluator_cycle()
        assert result["status"] == "ok"
        async with SessionLocal() as session:
            incidents = (
                await session.execute(
                    select(OpsIncident).where(OpsIncident.tenant_id == tenant_id)
                )
            ).scalars().all()
            assert incidents
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_jobs_retry_and_admin_endpoints(monkeypatch) -> None:
    tenant_id = f"t-operability-notify-{uuid4().hex}"
    _apply_env(monkeypatch)
    monkeypatch.setenv("NOTIFY_WEBHOOK_URLS_JSON", "[\"noop://test\"]")
    get_settings.cache_clear()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    _raw_other, other_headers, _other_user, _other_key = await create_test_api_key(
        tenant_id=f"{tenant_id}-other",
        role="admin",
        plan_id="enterprise",
    )

    from nexusrag.services.operability import notifications as notifications_module
    from nexusrag.services.operability.incidents import open_incident_for_alert

    async def _always_fail(*, destination, payload_bytes, headers):  # type: ignore[override]
        raise RuntimeError("forced failure")

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    monkeypatch.setattr(notifications_module, "_deliver", _always_fail)
    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with SessionLocal() as session:
            incident, _created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="worker.heartbeat.age_s",
                rule_id=None,
                severity="high",
                title="Worker stale",
                summary="heartbeat stale",
                details_json={"worker_heartbeat_age_s": 999},
                actor_id="tester",
                actor_role="admin",
                request_id="req-notify",
            )
            assert incident.id

        async with SessionLocal() as session:
            jobs = (
                await session.execute(select(NotificationJob).where(NotificationJob.tenant_id == tenant_id))
            ).scalars().all()
            assert len(jobs) == 1
            job_id = jobs[0].id

        async with SessionLocal() as session:
            processed = await process_notification_job(session=session, job_id=job_id)
            assert processed is not None

        async with SessionLocal() as session:
            refreshed = await session.get(NotificationJob, job_id)
            assert refreshed is not None
            assert refreshed.status in {"retrying", "dlq"}
            assert refreshed.attempt_count >= 1

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listing = await client.get("/v1/admin/notifications/jobs", headers=headers)
            assert listing.status_code == 200
            listed = listing.json()["data"]["items"]
            assert any(item["id"] == job_id for item in listed)

            detail = await client.get(f"/v1/admin/notifications/jobs/{job_id}", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["data"]["id"] == job_id

            retry = await client.post(f"/v1/admin/notifications/jobs/{job_id}/retry-now", headers=headers)
            assert retry.status_code == 200
            assert retry.json()["data"]["id"] == job_id
            assert retry.json()["data"]["status"] == "queued"

            attempts = await client.get(f"/v1/admin/notifications/jobs/{job_id}/attempts", headers=headers)
            assert attempts.status_code == 200
            assert attempts.json()["data"]["items"]

            cross_tenant_attempts = await client.get(
                f"/v1/admin/notifications/jobs/{job_id}/attempts",
                headers=other_headers,
            )
            assert cross_tenant_attempts.status_code == 404
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_tenant(f"{tenant_id}-other")
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_job_processes_successfully(monkeypatch) -> None:
    tenant_id = f"t-operability-notify-success-{uuid4().hex}"
    _apply_env(monkeypatch)
    monkeypatch.setenv("NOTIFY_WEBHOOK_URLS_JSON", "[\"noop://test-success\"]")
    get_settings.cache_clear()
    await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    from nexusrag.services.operability import notifications as notifications_module
    from nexusrag.services.operability.incidents import open_incident_for_alert

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)
    try:
        async with SessionLocal() as session:
            incident, _created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="worker.heartbeat.age_s",
                rule_id=None,
                severity="high",
                title="Worker stale",
                summary="heartbeat stale",
                details_json={"worker_heartbeat_age_s": 999},
                actor_id="tester",
                actor_role="admin",
                request_id="req-notify-success",
            )
            assert incident.id

        async with SessionLocal() as session:
            job = (
                await session.execute(
                    select(NotificationJob).where(NotificationJob.tenant_id == tenant_id).limit(1)
                )
            ).scalar_one()
            processed = await process_notification_job(session=session, job_id=job.id)
            assert processed is not None
            assert processed.status == "delivered"
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_delivery_contract_signature_and_attempt_hash(monkeypatch) -> None:
    tenant_id = f"t-operability-signature-{uuid4().hex}"
    _apply_env(monkeypatch)
    monkeypatch.setenv("KEYRING_MASTER_KEY", "local-test-key")
    get_settings.cache_clear()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    from nexusrag.services.operability import notifications as notifications_module
    from nexusrag.services.operability.incidents import open_incident_for_alert

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    captured: dict[str, str] = {}
    captured_body = b""

    async def _capture_delivery(*, destination, payload_bytes, headers):  # type: ignore[override]
        nonlocal captured, captured_body
        captured = {str(k): str(v) for k, v in headers.items()}
        captured_body = payload_bytes
        assert destination == "noop://signed"

    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)
    monkeypatch.setattr(notifications_module, "_deliver", _capture_delivery)
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_destination = await client.post(
                "/v1/admin/notifications/destinations",
                headers=headers,
                json={
                    "tenant_id": tenant_id,
                    "url": "noop://signed",
                    "headers_json": {"X-Custom-Header": "abc"},
                    "secret": "tenant-secret",
                },
            )
            assert create_destination.status_code == 200
            assert create_destination.json()["data"]["has_secret"] is True
            assert "secret" not in create_destination.json()["data"]

        async with SessionLocal() as session:
            incident, _created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="worker.heartbeat.age_s",
                rule_id=None,
                severity="high",
                title="Worker stale",
                summary="heartbeat stale",
                details_json={"worker_heartbeat_age_s": 999},
                actor_id="tester",
                actor_role="admin",
                request_id="req-signed",
            )
            assert incident.id

        async with SessionLocal() as session:
            job = (
                await session.execute(select(NotificationJob).where(NotificationJob.tenant_id == tenant_id).limit(1))
            ).scalar_one()
            processed = await process_notification_job(session=session, job_id=job.id)
            assert processed is not None
            assert processed.status == "delivered"
            job_id = processed.id

        assert captured["X-Notification-Id"] == job_id
        assert captured["X-Notification-Attempt"] == "1"
        assert captured["X-Notification-Event-Type"] == "incident.opened"
        assert captured["X-Notification-Tenant-Id"] == tenant_id
        assert captured["X-Custom-Header"] == "abc"
        expected_signature = "sha256=" + hmac.new(
            b"tenant-secret",
            captured_body,
            hashlib.sha256,
        ).hexdigest()
        assert captured["X-Notification-Signature"] == expected_signature

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            attempts = await client.get(f"/v1/admin/notifications/jobs/{job_id}/attempts", headers=headers)
            assert attempts.status_code == 200
            items = attempts.json()["data"]["items"]
            assert len(items) == 1
            assert items[0]["payload_sha256"] == hashlib.sha256(captured_body).hexdigest()
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_missing_signature_emits_audit_event(monkeypatch) -> None:
    tenant_id = f"t-operability-signature-missing-{uuid4().hex}"
    _apply_env(monkeypatch)
    await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    from nexusrag.services.operability import notifications as notifications_module
    from nexusrag.services.operability.incidents import open_incident_for_alert

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    captured_headers: dict[str, str] = {}

    async def _capture_delivery(*, destination, payload_bytes, headers):  # type: ignore[override]
        nonlocal captured_headers
        captured_headers = {str(k): str(v) for k, v in headers.items()}
        assert destination == "noop://unsigned"
        _ = payload_bytes

    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)
    monkeypatch.setattr(notifications_module, "_deliver", _capture_delivery)
    try:
        async with SessionLocal() as session:
            session.add(
                NotificationDestination(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    destination_url="noop://unsigned",
                    headers_json={},
                    secret_encrypted=None,
                    enabled=True,
                )
            )
            await session.commit()
            incident, _created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="worker.heartbeat.age_s",
                rule_id=None,
                severity="high",
                title="Worker stale",
                summary="heartbeat stale",
                details_json={"worker_heartbeat_age_s": 999},
                actor_id="tester",
                actor_role="admin",
                request_id="req-unsigned",
            )
            assert incident.id

        async with SessionLocal() as session:
            job = (
                await session.execute(select(NotificationJob).where(NotificationJob.tenant_id == tenant_id).limit(1))
            ).scalar_one()
            processed = await process_notification_job(session=session, job_id=job.id)
            assert processed is not None
            assert processed.status == "delivered"

        assert "X-Notification-Signature" not in captured_headers
        async with SessionLocal() as session:
            audit_rows = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.event_type == "notification.signature.missing",
                    )
                )
            ).scalars().all()
            assert audit_rows
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_destinations_are_tenant_scoped(monkeypatch) -> None:
    tenant_id = f"t-operability-dest-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create = await client.post(
                "/v1/admin/notifications/destinations",
                headers=headers,
                json={"tenant_id": tenant_id, "url": "noop://tenant-a", "secret": "super-secret"},
            )
            assert create.status_code == 200
            destination_id = create.json()["data"]["id"]
            assert create.json()["data"]["has_secret"] is True
            assert "secret_encrypted" not in create.json()["data"]

            list_resp = await client.get(
                f"/v1/admin/notifications/destinations?tenant_id={tenant_id}",
                headers=headers,
            )
            assert list_resp.status_code == 200
            items = list_resp.json()["data"]["items"]
            assert any(item["id"] == destination_id and item["enabled"] is True for item in items)
            assert all("secret_encrypted" not in item for item in items)

            disable = await client.patch(
                f"/v1/admin/notifications/destinations/{destination_id}",
                headers=headers,
                json={"enabled": False, "headers_json": {"X-Trace": "1"}},
            )
            assert disable.status_code == 200
            assert disable.json()["data"]["enabled"] is False
            assert disable.json()["data"]["headers_json"]["X-Trace"] == "1"

            delete_resp = await client.delete(
                f"/v1/admin/notifications/destinations/{destination_id}",
                headers=headers,
            )
            assert delete_resp.status_code == 200
            assert delete_resp.json()["data"]["deleted"] is True
        async with SessionLocal() as session:
            event_types = (
                await session.execute(
                    select(AuditEvent.event_type).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.event_type.in_(
                            [
                                "notification.destination.created",
                                "notification.destination.updated",
                                "notification.destination.deleted",
                            ]
                        ),
                    )
                )
            ).scalars().all()
            assert "notification.destination.created" in event_types
            assert "notification.destination.updated" in event_types
            assert "notification.destination.deleted" in event_types
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_routes_crud_is_tenant_scoped(monkeypatch) -> None:
    tenant_id = f"t-operability-routes-{uuid4().hex}"
    other_tenant_id = f"{tenant_id}-other"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    _raw_other, other_headers, _other_user, _other_key = await create_test_api_key(
        tenant_id=other_tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            destination = await client.post(
                "/v1/admin/notifications/destinations",
                headers=headers,
                json={"tenant_id": tenant_id, "url": "noop://route-crud-destination"},
            )
            assert destination.status_code == 200
            destination_id = destination.json()["data"]["id"]

            create_route = await client.post(
                "/v1/admin/notifications/routes",
                headers=headers,
                json={
                    "tenant_id": tenant_id,
                    "name": "critical-route",
                    "enabled": True,
                    "priority": 5,
                    "match_json": {"event_type": "incident.opened", "severity": ["high"]},
                    "destinations_json": [{"destination_id": destination_id}],
                },
            )
            assert create_route.status_code == 200
            route_id = create_route.json()["data"]["id"]

            list_route = await client.get(f"/v1/admin/notifications/routes?tenant_id={tenant_id}", headers=headers)
            assert list_route.status_code == 200
            assert any(item["id"] == route_id for item in list_route.json()["data"]["items"])

            patch_route = await client.patch(
                f"/v1/admin/notifications/routes/{route_id}",
                headers=headers,
                json={"enabled": False, "priority": 8},
            )
            assert patch_route.status_code == 200
            assert patch_route.json()["data"]["enabled"] is False
            assert patch_route.json()["data"]["priority"] == 8

            cross_tenant = await client.get(f"/v1/admin/notifications/routes?tenant_id={tenant_id}", headers=other_headers)
            assert cross_tenant.status_code == 404

            delete_route = await client.delete(f"/v1/admin/notifications/routes/{route_id}", headers=headers)
            assert delete_route.status_code == 200
            assert delete_route.json()["data"]["deleted"] is True
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_tenant(other_tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_incident_notifications_use_tenant_destinations(monkeypatch) -> None:
    tenant_id = f"t-operability-routing-{uuid4().hex}"
    _apply_env(monkeypatch)
    monkeypatch.setenv("NOTIFY_WEBHOOK_URLS_JSON", "[\"noop://global-fallback\"]")
    get_settings.cache_clear()
    await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    from nexusrag.services.operability import notifications as notifications_module
    from nexusrag.services.operability.incidents import open_incident_for_alert

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)
    try:
        async with SessionLocal() as session:
            session.add(
                NotificationDestination(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    destination_url="noop://tenant-override",
                    enabled=True,
                )
            )
            await session.commit()
            incident, created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="queue.depth",
                rule_id=None,
                severity="high",
                title="Queue depth high",
                summary="queue depth threshold exceeded",
                details_json={"queue_depth": 999},
                actor_id="tester",
                actor_role="admin",
                request_id="req-routing",
            )
            assert created is True
            assert incident.id

        async with SessionLocal() as session:
            jobs = (
                await session.execute(
                    select(NotificationJob).where(NotificationJob.tenant_id == tenant_id)
                )
            ).scalars().all()
            assert jobs
            assert {job.destination for job in jobs} == {"noop://tenant-override"}
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_routes_control_destination_order(monkeypatch) -> None:
    tenant_id = f"t-operability-route-order-{uuid4().hex}"
    _apply_env(monkeypatch)
    get_settings.cache_clear()
    await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    from nexusrag.services.operability import notifications as notifications_module
    from nexusrag.services.operability.incidents import open_incident_for_alert

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)
    try:
        async with SessionLocal() as session:
            destination_one = NotificationDestination(
                id=uuid4().hex,
                tenant_id=tenant_id,
                destination_url="noop://route-specific",
                enabled=True,
            )
            destination_two = NotificationDestination(
                id=uuid4().hex,
                tenant_id=tenant_id,
                destination_url="noop://route-wildcard",
                enabled=True,
            )
            session.add_all([destination_one, destination_two])
            await session.commit()
            session.add_all(
                [
                    NotificationRoute(
                        id=uuid4().hex,
                        tenant_id=tenant_id,
                        name="specific-high",
                        enabled=True,
                        priority=10,
                        match_json={"event_type": "incident.opened", "severity": ["high"]},
                        destinations_json=[{"destination_id": destination_one.id}],
                    ),
                    NotificationRoute(
                        id=uuid4().hex,
                        tenant_id=tenant_id,
                        name="wildcard-high",
                        enabled=True,
                        priority=20,
                        match_json={"event_type": "*", "severity": ["high", "critical"]},
                        destinations_json=[{"destination_id": destination_two.id}],
                    ),
                ]
            )
            await session.commit()
            incident, created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="queue.depth",
                rule_id=None,
                severity="high",
                title="Queue depth high",
                summary="queue depth threshold exceeded",
                details_json={"queue_depth": 999},
                actor_id="tester",
                actor_role="admin",
                request_id="req-route-order",
            )
            assert created is True
            assert incident.id

        async with SessionLocal() as session:
            jobs = (
                await session.execute(
                    select(NotificationJob)
                    .where(NotificationJob.tenant_id == tenant_id)
                    .order_by(NotificationJob.created_at.asc(), NotificationJob.id.asc())
                )
            ).scalars().all()
            assert [job.destination for job in jobs] == ["noop://route-specific", "noop://route-wildcard"]
    finally:
        await _cleanup_tenant(tenant_id)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_notification_dlq_and_replay_are_tenant_scoped(monkeypatch) -> None:
    tenant_id = f"t-operability-dlq-{uuid4().hex}"
    other_tenant_id = f"{tenant_id}-other"
    _apply_env(monkeypatch)
    monkeypatch.setenv("NOTIFY_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("NOTIFY_WEBHOOK_URLS_JSON", "[\"noop://dlq-test\"]")
    get_settings.cache_clear()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    _other_raw, other_headers, _other_user, _other_key = await create_test_api_key(
        tenant_id=other_tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    from nexusrag.services.operability import notifications as notifications_module
    from nexusrag.services.operability.incidents import open_incident_for_alert

    async def _always_fail(*, destination, payload_bytes, headers):  # type: ignore[override]
        raise RuntimeError("forced dlq failure")

    async def _enqueue_stub(*, job_id: str, defer_ms: int = 0) -> bool:
        return True

    monkeypatch.setattr(notifications_module, "_deliver", _always_fail)
    monkeypatch.setattr(notifications_module, "enqueue_notification_job", _enqueue_stub)

    app = create_app()
    transport = ASGITransport(app=app)
    try:
        async with SessionLocal() as session:
            incident, _created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="worker.heartbeat.age_s",
                rule_id=None,
                severity="high",
                title="Worker stale",
                summary="heartbeat stale",
                details_json={"worker_heartbeat_age_s": 999},
                actor_id="tester",
                actor_role="admin",
                request_id="req-dlq",
            )
            assert incident.id

        async with SessionLocal() as session:
            job = (
                await session.execute(
                    select(NotificationJob).where(NotificationJob.tenant_id == tenant_id).limit(1)
                )
            ).scalar_one()
            processed = await process_notification_job(session=session, job_id=job.id)
            assert processed is not None
            assert processed.status == "dlq"

        async with SessionLocal() as session:
            dead_letter = (
                await session.execute(
                    select(NotificationDeadLetter).where(NotificationDeadLetter.tenant_id == tenant_id).limit(1)
                )
            ).scalar_one()
            assert dead_letter.job_id
            dead_letter_id = dead_letter.id

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listing = await client.get(f"/v1/admin/notifications/dlq?tenant_id={tenant_id}", headers=headers)
            assert listing.status_code == 200
            items = listing.json()["data"]["items"]
            assert any(item["id"] == dead_letter_id for item in items)

            cross_tenant = await client.get(f"/v1/admin/notifications/dlq/{dead_letter_id}", headers=other_headers)
            assert cross_tenant.status_code == 404

            replay = await client.post(f"/v1/admin/notifications/dlq/{dead_letter_id}/replay", headers=headers)
            assert replay.status_code == 200
            replay_payload = replay.json()["data"]
            assert replay_payload["dead_letter_id"] == dead_letter_id
            assert replay_payload["created_job_ids"]

        async with SessionLocal() as session:
            replayed_jobs = (
                await session.execute(
                    select(NotificationJob)
                    .where(NotificationJob.tenant_id == tenant_id)
                    .order_by(NotificationJob.created_at.asc(), NotificationJob.id.asc())
                )
            ).scalars().all()
            assert len(replayed_jobs) == 2
    finally:
        await _cleanup_tenant(tenant_id)
        await _cleanup_tenant(other_tenant_id)
        get_settings.cache_clear()
