from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import NotificationAttempt, NotificationDestination, NotificationJob
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.audit import record_event
from nexusrag.services.entitlements import FEATURE_OPS_ADMIN, get_effective_entitlements

_READY_STATUSES = ("queued", "retrying")
_notification_queue_pool = None
_notification_queue_pool_loop = None
_notification_queue_lock = asyncio.Lock()


def _utc_now() -> datetime:
    # Keep notification scheduling and retry bookkeeping in UTC for deterministic comparisons.
    return datetime.now(timezone.utc)


def _global_notification_destinations() -> list[str]:
    # Resolve global fallback destinations from config for tenants without explicit routing rows.
    settings = get_settings()
    parsed: list[str] = []
    try:
        raw = json.loads(settings.notify_webhook_urls_json)
    except json.JSONDecodeError:
        raw = []
    if isinstance(raw, list):
        parsed.extend(str(value).strip() for value in raw if isinstance(value, str) and value.strip())

    adapter = settings.ops_notification_adapter.strip().lower()
    if adapter == "webhook" and settings.ops_notification_webhook_url:
        parsed.append(settings.ops_notification_webhook_url.strip())
    if not parsed and adapter == "noop":
        parsed.append("noop://default")

    # Preserve config order while de-duplicating destinations.
    deduped: list[str] = []
    seen: set[str] = set()
    for destination in parsed:
        if destination in seen:
            continue
        seen.add(destination)
        deduped.append(destination)
    return deduped


def _validate_destination_url(destination_url: str) -> str:
    # Restrict destinations to explicit URL schemes so notification routing never accepts ambiguous targets.
    normalized = destination_url.strip()
    if normalized.startswith(("http://", "https://", "noop://")):
        return normalized
    raise ValueError("destination_url must start with http://, https://, or noop://")


async def resolve_notification_destinations(*, session: AsyncSession, tenant_id: str) -> list[str]:
    # Prefer tenant-scoped destinations and fall back to global defaults for backward compatibility.
    rows = (
        await session.execute(
            select(NotificationDestination)
            .where(
                NotificationDestination.tenant_id == tenant_id,
                NotificationDestination.enabled.is_(True),
            )
            .order_by(NotificationDestination.created_at.asc())
        )
    ).scalars().all()
    if rows:
        return [row.destination_url for row in rows]
    return _global_notification_destinations()


async def list_notification_destinations(
    *,
    session: AsyncSession,
    tenant_id: str,
) -> list[NotificationDestination]:
    # Keep destination listing tenant-scoped to prevent routing disclosure across tenants.
    rows = (
        await session.execute(
            select(NotificationDestination)
            .where(NotificationDestination.tenant_id == tenant_id)
            .order_by(NotificationDestination.created_at.asc())
        )
    ).scalars().all()
    return list(rows)


async def create_notification_destination(
    *,
    session: AsyncSession,
    tenant_id: str,
    destination_url: str,
) -> NotificationDestination:
    # Enforce canonical URL validation and uniqueness for deterministic destination routing.
    row = NotificationDestination(
        id=uuid4().hex,
        tenant_id=tenant_id,
        destination_url=_validate_destination_url(destination_url),
        enabled=True,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = (
            await session.execute(
                select(NotificationDestination).where(
                    NotificationDestination.tenant_id == tenant_id,
                    NotificationDestination.destination_url == row.destination_url,
                )
            )
        ).scalar_one()
        return existing
    await session.refresh(row)
    return row


async def patch_notification_destination(
    *,
    session: AsyncSession,
    tenant_id: str,
    destination_id: str,
    enabled: bool,
) -> NotificationDestination | None:
    # Apply enable/disable toggles in place so destination identifiers remain stable for operators.
    row = await session.get(NotificationDestination, destination_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    row.enabled = bool(enabled)
    await session.commit()
    await session.refresh(row)
    return row


async def delete_notification_destination(
    *,
    session: AsyncSession,
    tenant_id: str,
    destination_id: str,
) -> bool:
    # Delete only tenant-owned destinations and return a boolean for idempotent API semantics.
    row = await session.get(NotificationDestination, destination_id)
    if row is None or row.tenant_id != tenant_id:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def get_notification_queue_pool():
    # Cache ARQ Redis pool per event loop to avoid reconnect churn in API and worker code paths.
    global _notification_queue_pool, _notification_queue_pool_loop
    current_loop = asyncio.get_running_loop()
    if _notification_queue_pool is not None and _notification_queue_pool_loop == current_loop:
        return _notification_queue_pool
    if _notification_queue_pool is not None and _notification_queue_pool_loop != current_loop:
        _notification_queue_pool = None
    async with _notification_queue_lock:
        if _notification_queue_pool is None:
            settings = get_settings()
            _notification_queue_pool = await create_pool(
                RedisSettings.from_dsn(settings.redis_url),
                default_queue_name=settings.notify_queue_name,
            )
            _notification_queue_pool_loop = current_loop
    return _notification_queue_pool


async def enqueue_notification_job(*, job_id: str, defer_ms: int = 0) -> bool:
    # Publish notification job ids onto ARQ for async delivery while DB rows remain the source of truth.
    settings = get_settings()
    defer_delta = timedelta(milliseconds=max(0, int(defer_ms)))
    try:
        redis = await get_notification_queue_pool()
        await redis.enqueue_job(
            "deliver_notification_job",
            job_id,
            _queue_name=settings.notify_queue_name,
            _defer_by=defer_delta if defer_delta.total_seconds() > 0 else None,
        )
        return True
    except Exception:  # noqa: BLE001 - keep enqueue best-effort and rely on due-job requeue fallback.
        return False


def dedupe_window_start(*, now: datetime, window_seconds: int) -> datetime:
    # Round to a stable bucket boundary so retries and duplicate incident triggers collapse consistently.
    bucket = max(1, int(window_seconds))
    epoch = int(now.timestamp())
    rounded = epoch - (epoch % bucket)
    return datetime.fromtimestamp(rounded, tz=timezone.utc)


def retry_backoff_ms(*, job_id: str, attempt_no: int) -> int:
    # Use exponential backoff with deterministic jitter to keep tests reproducible and avoid stampedes.
    settings = get_settings()
    base = max(1, int(settings.notify_backoff_ms))
    cap = max(base, int(settings.notify_backoff_max_ms))
    exponent = max(0, int(attempt_no) - 1)
    backoff = min(cap, base * (2**exponent))
    digest = hashlib.sha256(f"{job_id}:{attempt_no}".encode("utf-8")).hexdigest()
    jitter = int(digest[:8], 16) % 251
    return min(cap, backoff + jitter)


async def send_operability_notification(
    *,
    session: AsyncSession,
    tenant_id: str | None,
    event_type: str,
    payload: dict[str, Any],
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> None:
    # Enqueue durable notification jobs so alerting paths never block on outbound delivery.
    if tenant_id is None:
        return
    entitlements = await get_effective_entitlements(session, tenant_id)
    entitlement = entitlements.get(FEATURE_OPS_ADMIN)
    if entitlement is None or not entitlement.enabled:
        return
    destinations = await resolve_notification_destinations(session=session, tenant_id=tenant_id)
    if not destinations:
        return

    now = _utc_now()
    window_start = dedupe_window_start(now=now, window_seconds=get_settings().notify_dedupe_window_s)
    incident_id = payload.get("incident_id")
    if not isinstance(incident_id, str):
        incident_id = None
    alert_event_id = payload.get("alert_event_id")
    if not isinstance(alert_event_id, str):
        alert_event_id = None
    dedupe_key = str(payload.get("dedupe_key") or event_type)

    for destination in destinations:
        async with SessionLocal() as job_session:
            job = NotificationJob(
                id=uuid4().hex,
                tenant_id=tenant_id,
                incident_id=incident_id,
                alert_event_id=alert_event_id,
                destination=destination,
                dedupe_key=dedupe_key,
                dedupe_window_start=window_start,
                payload_json={
                    "event_type": event_type,
                    "tenant_id": tenant_id,
                    "payload": payload,
                },
                status="queued",
                next_attempt_at=now,
                attempt_count=0,
                last_error=None,
            )
            job_session.add(job)
            try:
                await job_session.commit()
            except IntegrityError:
                # Drop duplicate jobs inside the dedupe window so repeated incident updates don't fan out endlessly.
                await job_session.rollback()
                continue
            await record_event(
                session=job_session,
                tenant_id=tenant_id,
                actor_type="system",
                actor_id=actor_id,
                actor_role=actor_role,
                event_type="notification.job.enqueued",
                outcome="success",
                resource_type="notification_job",
                resource_id=job.id,
                request_id=request_id,
                metadata={"destination": destination, "event_type": event_type, "dedupe_key": dedupe_key},
                commit=True,
                best_effort=True,
            )
        enqueued = await enqueue_notification_job(job_id=job.id)
        if not enqueued:
            async with SessionLocal() as fallback_session:
                # Record enqueue degradation so operators can distinguish transport outages from endpoint failures.
                await record_event(
                    session=fallback_session,
                    tenant_id=tenant_id,
                    actor_type="system",
                    actor_id=actor_id,
                    actor_role=actor_role,
                    event_type="notification.job.enqueue_degraded",
                    outcome="failure",
                    resource_type="notification_job",
                    resource_id=job.id,
                    request_id=request_id,
                    metadata={"destination": destination},
                    commit=True,
                    best_effort=True,
                )


async def enqueue_due_notification_jobs(*, session: AsyncSession, limit: int = 50) -> int:
    # Re-enqueue overdue jobs to recover from transient worker outages without changing durable DB state.
    now = _utc_now()
    stale_cutoff = now - timedelta(seconds=max(1, int(get_settings().notify_worker_poll_interval_s)))
    rows = (
        await session.execute(
            select(NotificationJob.id)
            .where(
                NotificationJob.status.in_(_READY_STATUSES),
                NotificationJob.next_attempt_at <= now,
                NotificationJob.updated_at <= stale_cutoff,
            )
            .order_by(NotificationJob.next_attempt_at.asc(), NotificationJob.created_at.asc())
            .limit(max(1, limit))
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    job_ids = [str(row) for row in rows]
    if not job_ids:
        return 0
    await session.execute(
        update(NotificationJob)
        .where(NotificationJob.id.in_(job_ids))
        .values(updated_at=now)
    )
    await session.commit()
    count = 0
    for job_id in job_ids:
        if await enqueue_notification_job(job_id=job_id):
            count += 1
    return count


async def _deliver(*, destination: str, body: dict[str, Any], notification_id: str) -> None:
    # Keep delivery adapters small and deterministic: noop for local/dev, webhook for live integrations.
    if destination.startswith("noop://"):
        return
    timeout_s = max(0.2, get_settings().ext_call_timeout_ms / 1000.0)
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            destination,
            json=body,
            headers={"X-Notification-Id": notification_id},
        )
        response.raise_for_status()


async def _claim_notification_job(*, session: AsyncSession, job_id: str) -> NotificationJob | None:
    # Transition queued/retrying rows to sending with compare-and-set semantics to prevent duplicate processing.
    now = _utc_now()
    updated = await session.execute(
        update(NotificationJob)
        .where(
            NotificationJob.id == job_id,
            NotificationJob.status.in_(_READY_STATUSES),
            NotificationJob.next_attempt_at <= now,
        )
        .values(status="sending", updated_at=now)
    )
    await session.commit()
    if int(updated.rowcount or 0) == 0:
        return None
    return await session.get(NotificationJob, job_id)


async def process_notification_job(*, session: AsyncSession, job_id: str) -> NotificationJob | None:
    # Execute one delivery attempt and persist both job state transitions and immutable attempt history.
    job = await _claim_notification_job(session=session, job_id=job_id)
    if job is None:
        return None
    now = _utc_now()
    attempt_no = int(job.attempt_count) + 1
    attempt = NotificationAttempt(
        job_id=job.id,
        attempt_no=attempt_no,
        started_at=now,
        finished_at=None,
        outcome="running",
        error=None,
    )
    session.add(attempt)
    await session.flush()

    try:
        await _deliver(destination=job.destination, body=job.payload_json or {}, notification_id=job.id)
    except Exception as exc:  # noqa: BLE001 - delivery failures are isolated to job state updates.
        attempt.finished_at = _utc_now()
        attempt.outcome = "failure"
        attempt.error = str(exc)
        job.attempt_count = attempt_no
        job.last_error = str(exc)
        max_attempts = max(1, int(get_settings().notify_max_attempts))
        if attempt_no >= max_attempts:
            job.status = "gave_up"
            job.next_attempt_at = attempt.finished_at
            event_type = "notification.job.gave_up"
        else:
            delay_ms = retry_backoff_ms(job_id=job.id, attempt_no=attempt_no)
            job.status = "retrying"
            job.next_attempt_at = attempt.finished_at + timedelta(milliseconds=delay_ms)
            event_type = "notification.job.failed"
        await session.commit()
        await session.refresh(job)
        if job.status == "retrying":
            await enqueue_notification_job(job_id=job.id, defer_ms=retry_backoff_ms(job_id=job.id, attempt_no=attempt_no))
        await record_event(
            session=session,
            tenant_id=job.tenant_id,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type=event_type,
            outcome="failure",
            resource_type="notification_job",
            resource_id=job.id,
            request_id=None,
            metadata={"attempt_no": attempt_no, "destination": job.destination},
            commit=True,
            best_effort=True,
        )
        return job

    attempt.finished_at = _utc_now()
    attempt.outcome = "success"
    job.attempt_count = attempt_no
    job.last_error = None
    job.status = "succeeded"
    job.next_attempt_at = attempt.finished_at
    await session.commit()
    await session.refresh(job)
    await record_event(
        session=session,
        tenant_id=job.tenant_id,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="notification.job.succeeded",
        outcome="success",
        resource_type="notification_job",
        resource_id=job.id,
        request_id=None,
        metadata={"attempt_no": attempt_no, "destination": job.destination},
        commit=True,
        best_effort=True,
    )
    return job


async def list_notification_jobs(
    *,
    session: AsyncSession,
    tenant_id: str,
    status_filter: str | None,
    limit: int = 100,
) -> list[NotificationJob]:
    # Scope queue visibility by tenant to preserve operator boundary guarantees.
    query = select(NotificationJob).where(NotificationJob.tenant_id == tenant_id)
    if status_filter:
        query = query.where(NotificationJob.status == status_filter)
    rows = (
        await session.execute(
            query.order_by(NotificationJob.created_at.desc()).limit(max(1, min(limit, 500)))
        )
    ).scalars().all()
    return list(rows)


async def get_notification_job(
    *,
    session: AsyncSession,
    tenant_id: str,
    job_id: str,
) -> NotificationJob | None:
    # Enforce tenant ownership checks before returning queue details.
    row = await session.get(NotificationJob, job_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


async def retry_notification_job_now(
    *,
    session: AsyncSession,
    tenant_id: str,
    job_id: str,
) -> NotificationJob | None:
    # Allow operators to force immediate retries while preserving attempt history and idempotent state machine rules.
    row = await get_notification_job(session=session, tenant_id=tenant_id, job_id=job_id)
    if row is None:
        return None
    row.status = "retrying"
    row.next_attempt_at = _utc_now()
    await session.commit()
    await session.refresh(row)
    await enqueue_notification_job(job_id=row.id)
    return row


async def notification_queue_summary(*, session: AsyncSession, tenant_id: str) -> dict[str, int]:
    # Expose compact queue counters for /ops surfaces without returning full job payloads.
    queued = await session.scalar(
        select(func.count())
        .select_from(NotificationJob)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationJob.status.in_(["queued", "retrying", "sending"]),
        )
    )
    failed_last_hour = await session.scalar(
        select(func.count())
        .select_from(NotificationJob)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationJob.status.in_(["gave_up", "failed"]),
            NotificationJob.updated_at >= (_utc_now() - timedelta(hours=1)),
        )
    )
    return {"queued": int(queued or 0), "failed_last_hour": int(failed_last_hour or 0)}
