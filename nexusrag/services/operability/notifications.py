from __future__ import annotations

import asyncio
import hashlib
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
from nexusrag.domain.models import (
    NotificationAttempt,
    NotificationDeadLetter,
    NotificationDestination,
    NotificationJob,
    NotificationRoute,
)
from nexusrag.services.audit import record_event, sanitize_metadata
from nexusrag.services.entitlements import FEATURE_OPS_ADMIN, get_effective_entitlements
from nexusrag.services.notifications.routing import resolve_destinations
from nexusrag.services.rollouts import resolve_kill_switch

_READY_STATUSES = ("queued", "retrying")
_notification_queue_pool = None
_notification_queue_pool_loop = None
_notification_queue_lock = asyncio.Lock()


def _utc_now() -> datetime:
    # Keep notification scheduling and retry bookkeeping in UTC for deterministic comparisons.
    return datetime.now(timezone.utc)


def _validate_destination_url(destination_url: str) -> str:
    # Restrict destinations to explicit URL schemes so notification routing never accepts ambiguous targets.
    normalized = destination_url.strip()
    if normalized.startswith(("http://", "https://", "noop://")):
        return normalized
    raise ValueError("destination_url must start with http://, https://, or noop://")


async def resolve_notification_destinations(*, session: AsyncSession, tenant_id: str) -> list[str]:
    # Keep legacy helper contract by delegating to the canonical route-based destination resolver.
    resolved = await resolve_destinations(
        session=session,
        tenant_id=tenant_id,
        event_type="*",
        severity="low",
    )
    return [row.destination_url for row in resolved]


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


def _normalize_match_json(match_json: dict[str, Any] | None) -> dict[str, Any]:
    # Normalize route filters so evaluation semantics stay deterministic across admin updates.
    if match_json is None:
        return {}
    if not isinstance(match_json, dict):
        raise ValueError("match_json must be an object")
    allowed_keys = {"event_type", "severity", "source", "category"}
    normalized: dict[str, Any] = {}
    for key, raw in match_json.items():
        if key not in allowed_keys:
            raise ValueError(f"Unsupported match_json key: {key}")
        if isinstance(raw, str):
            value = raw.strip()
            if value:
                normalized[key] = value.lower()
            continue
        if isinstance(raw, list):
            values = [str(item).strip().lower() for item in raw if str(item).strip()]
            if values:
                normalized[key] = values
            continue
        raise ValueError(f"match_json.{key} must be a string or list of strings")
    severity_values = normalized.get("severity")
    if isinstance(severity_values, str):
        if severity_values not in {"low", "medium", "high", "critical"}:
            raise ValueError("match_json.severity contains unsupported value")
    elif isinstance(severity_values, list):
        invalid = [value for value in severity_values if value not in {"low", "medium", "high", "critical"}]
        if invalid:
            raise ValueError("match_json.severity contains unsupported value")
    return normalized


def _normalize_route_destinations(raw: list[Any] | None) -> list[dict[str, Any]]:
    # Store route destination references in one normalized shape to keep ordering explicit and replay-safe.
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("destinations_json must be an array")
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            destination_id = item.strip()
            if destination_id:
                normalized.append({"destination_id": destination_id, "enabled": True})
            continue
        if isinstance(item, dict):
            destination_id = str(item.get("destination_id", "")).strip()
            if not destination_id:
                raise ValueError("destinations_json items require destination_id")
            normalized.append(
                {
                    "destination_id": destination_id,
                    "enabled": bool(item.get("enabled", True)),
                }
            )
            continue
        raise ValueError("destinations_json items must be destination ids or objects")
    if not normalized:
        raise ValueError("destinations_json must include at least one destination")
    return normalized


async def _validate_route_destination_ids(
    *,
    session: AsyncSession,
    tenant_id: str,
    destinations_json: list[dict[str, Any]],
) -> None:
    # Reject unknown destination ids so route evaluation never references cross-tenant or missing rows.
    destination_ids = [str(item.get("destination_id")) for item in destinations_json]
    rows = (
        await session.execute(
            select(NotificationDestination.id).where(
                NotificationDestination.tenant_id == tenant_id,
                NotificationDestination.id.in_(destination_ids),
            )
        )
    ).scalars().all()
    known = set(rows)
    unknown = [destination_id for destination_id in destination_ids if destination_id not in known]
    if unknown:
        raise ValueError("destinations_json references unknown destination_id")


async def list_notification_routes(*, session: AsyncSession, tenant_id: str) -> list[NotificationRoute]:
    # Return tenant routes in evaluation order so admins can reason about effective precedence.
    rows = (
        await session.execute(
            select(NotificationRoute)
            .where(NotificationRoute.tenant_id == tenant_id)
            .order_by(NotificationRoute.priority.asc(), NotificationRoute.created_at.asc(), NotificationRoute.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def create_notification_route(
    *,
    session: AsyncSession,
    tenant_id: str,
    name: str,
    enabled: bool,
    priority: int,
    match_json: dict[str, Any] | None,
    destinations_json: list[Any] | None,
) -> NotificationRoute:
    # Create route rows with pre-validated filters and destination references to keep matching deterministic.
    normalized_match = _normalize_match_json(match_json)
    normalized_destinations = _normalize_route_destinations(destinations_json)
    await _validate_route_destination_ids(
        session=session,
        tenant_id=tenant_id,
        destinations_json=normalized_destinations,
    )
    row = NotificationRoute(
        id=uuid4().hex,
        tenant_id=tenant_id,
        name=name.strip() or "route",
        enabled=bool(enabled),
        priority=int(priority),
        match_json=normalized_match,
        destinations_json=normalized_destinations,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def patch_notification_route(
    *,
    session: AsyncSession,
    tenant_id: str,
    route_id: str,
    updates: dict[str, Any],
) -> NotificationRoute | None:
    # Apply partial route updates atomically while preserving tenant boundaries and destination integrity.
    row = await session.get(NotificationRoute, route_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    if "name" in updates and updates["name"] is not None:
        row.name = str(updates["name"]).strip() or row.name
    if "enabled" in updates and updates["enabled"] is not None:
        row.enabled = bool(updates["enabled"])
    if "priority" in updates and updates["priority"] is not None:
        row.priority = int(updates["priority"])
    if "match_json" in updates:
        row.match_json = _normalize_match_json(updates.get("match_json"))
    if "destinations_json" in updates:
        normalized_destinations = _normalize_route_destinations(updates.get("destinations_json"))
        await _validate_route_destination_ids(
            session=session,
            tenant_id=tenant_id,
            destinations_json=normalized_destinations,
        )
        row.destinations_json = normalized_destinations
    await session.commit()
    await session.refresh(row)
    return row


async def delete_notification_route(*, session: AsyncSession, tenant_id: str, route_id: str) -> bool:
    # Delete only tenant-owned routes and return a stable boolean for idempotent API handlers.
    row = await session.get(NotificationRoute, route_id)
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


async def _is_notification_delivery_paused() -> bool:
    # Reuse rollout kill-switch semantics so delivery can be paused quickly during incident storms.
    return await resolve_kill_switch("kill.notifications")


def _is_non_retriable_delivery_error(exc: Exception) -> tuple[bool, str]:
    # Treat selected HTTP 4xx responses as poison events and dead-letter immediately.
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = int(exc.response.status_code)
        if status_code in {404, 410}:
            return True, f"http_{status_code}_non_retriable"
    return False, "retryable_failure"


async def _dead_letter_job(
    *,
    session: AsyncSession,
    job: NotificationJob,
    reason: str,
    last_error: str | None,
) -> NotificationDeadLetter:
    # Persist a redacted DLQ payload so replay/debug flows never rely on raw sensitive webhook content.
    payload = sanitize_metadata(job.payload_json or {})
    row = NotificationDeadLetter(
        id=uuid4().hex,
        tenant_id=job.tenant_id,
        job_id=job.id,
        reason=reason,
        last_error=last_error,
        payload_json=payload if isinstance(payload, dict) else {"payload": payload},
    )
    session.add(row)
    return row


async def _create_notification_jobs(
    *,
    session: AsyncSession,
    tenant_id: str,
    event_type: str,
    severity: str,
    payload: dict[str, Any],
    source: str | None,
    category: str | None,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> list[str]:
    # Use one destination resolver for create/replay flows so routing behavior is consistent and testable.
    destinations = await resolve_destinations(
        session=session,
        tenant_id=tenant_id,
        event_type=event_type,
        severity=severity,
        source=source,
        category=category,
        metadata=payload,
    )
    if not destinations:
        return []

    now = _utc_now()
    window_start = dedupe_window_start(now=now, window_seconds=get_settings().notify_dedupe_window_s)
    incident_id = payload.get("incident_id")
    if not isinstance(incident_id, str):
        incident_id = None
    alert_event_id = payload.get("alert_event_id")
    if not isinstance(alert_event_id, str):
        alert_event_id = None
    dedupe_key = str(payload.get("dedupe_key") or event_type)
    created_job_ids: list[str] = []
    for resolved in destinations:
        job = NotificationJob(
            id=uuid4().hex,
            tenant_id=tenant_id,
            incident_id=incident_id,
            alert_event_id=alert_event_id,
            destination=resolved.destination_url,
            dedupe_key=dedupe_key,
            dedupe_window_start=window_start,
            payload_json={
                "event_type": event_type,
                "severity": severity,
                "source": source,
                "category": category,
                "tenant_id": tenant_id,
                "payload": payload,
                "route_id": resolved.route_id,
                "destination_id": resolved.destination_id,
                "destination_source": resolved.source,
            },
            status="queued",
            next_attempt_at=now,
            attempt_count=0,
            last_error=None,
        )
        session.add(job)
        try:
            await session.commit()
        except IntegrityError:
            # Drop duplicate jobs inside the dedupe window so repeated incident updates don't fan out endlessly.
            await session.rollback()
            continue
        created_job_ids.append(job.id)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="notification.job.enqueued",
            outcome="success",
            resource_type="notification_job",
            resource_id=job.id,
            request_id=request_id,
            metadata={
                "destination": resolved.destination_url,
                "event_type": event_type,
                "dedupe_key": dedupe_key,
                "route_id": resolved.route_id,
                "destination_source": resolved.source,
            },
            commit=True,
            best_effort=True,
        )
    for job_id in created_job_ids:
        enqueued = await enqueue_notification_job(job_id=job_id)
        if enqueued:
            continue
        # Record enqueue degradation so operators can distinguish transport outages from endpoint failures.
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="notification.job.enqueue_degraded",
            outcome="failure",
            resource_type="notification_job",
            resource_id=job_id,
            request_id=request_id,
            metadata={"event_type": event_type},
            commit=True,
            best_effort=True,
        )
    return created_job_ids


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
    if await _is_notification_delivery_paused():
        # Drop enqueue attempts while paused so outbound delivery storms can be halted deterministically.
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="notification.delivery.paused",
            outcome="failure",
            resource_type="notification_job",
            resource_id=None,
            request_id=request_id,
            metadata={"event_type": event_type},
            commit=True,
            best_effort=True,
        )
        return
    severity = str(payload.get("severity") or "low")
    source = payload.get("source")
    category = payload.get("category")
    await _create_notification_jobs(
        session=session,
        tenant_id=tenant_id,
        event_type=event_type,
        severity=severity,
        payload=payload,
        source=str(source) if isinstance(source, str) else None,
        category=str(category) if isinstance(category, str) else None,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
    )


async def enqueue_due_notification_jobs(*, session: AsyncSession, limit: int = 50) -> int:
    # Re-enqueue overdue jobs to recover from transient worker outages without changing durable DB state.
    if await _is_notification_delivery_paused():
        return 0
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
    if await _is_notification_delivery_paused():
        # Keep jobs queued when paused so operators can resume without losing durable records.
        return None
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
        non_retriable, reason = _is_non_retriable_delivery_error(exc)
        if non_retriable or attempt_no >= max_attempts:
            job.status = "dead_lettered"
            job.next_attempt_at = attempt.finished_at
            await _dead_letter_job(
                session=session,
                job=job,
                reason=reason if non_retriable else "max_attempts_exceeded",
                last_error=str(exc),
            )
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
            metadata={"attempt_no": attempt_no, "destination": job.destination, "status": job.status},
            commit=True,
            best_effort=True,
        )
        if job.status == "dead_lettered":
            await record_event(
                session=session,
                tenant_id=job.tenant_id,
                actor_type="system",
                actor_id=None,
                actor_role=None,
                event_type="notification.job.dead_lettered",
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


async def list_notification_dead_letters(
    *,
    session: AsyncSession,
    tenant_id: str,
    limit: int = 100,
) -> list[NotificationDeadLetter]:
    # Keep DLQ listing tenant-scoped for safe operator replay workflows.
    rows = (
        await session.execute(
            select(NotificationDeadLetter)
            .where(NotificationDeadLetter.tenant_id == tenant_id)
            .order_by(NotificationDeadLetter.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).scalars().all()
    return list(rows)


async def get_notification_dead_letter(
    *,
    session: AsyncSession,
    tenant_id: str,
    dead_letter_id: str,
) -> NotificationDeadLetter | None:
    # Return DLQ rows only for the owning tenant.
    row = await session.get(NotificationDeadLetter, dead_letter_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


async def replay_dead_letter(
    *,
    session: AsyncSession,
    tenant_id: str,
    dead_letter_id: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> dict[str, Any] | None:
    # Replay DLQ records through the same routing resolver used for new notifications.
    if await _is_notification_delivery_paused():
        raise RuntimeError("Notification delivery is paused by kill.notifications")
    dead_letter = await get_notification_dead_letter(
        session=session,
        tenant_id=tenant_id,
        dead_letter_id=dead_letter_id,
    )
    if dead_letter is None:
        return None
    payload_json = dead_letter.payload_json or {}
    if not isinstance(payload_json, dict):
        payload_json = {}
    replay_payload = payload_json.get("payload")
    if not isinstance(replay_payload, dict):
        replay_payload = {}
    replay_payload = {
        **replay_payload,
        "replayed_from_dead_letter_id": dead_letter.id,
        "replayed_from_job_id": dead_letter.job_id,
    }
    event_type = str(payload_json.get("event_type") or "incident.opened")
    severity = str(payload_json.get("severity") or "low")
    source_value = payload_json.get("source")
    category_value = payload_json.get("category")
    created_job_ids = await _create_notification_jobs(
        session=session,
        tenant_id=tenant_id,
        event_type=event_type,
        severity=severity,
        payload=replay_payload,
        source=str(source_value) if isinstance(source_value, str) else None,
        category=str(category_value) if isinstance(category_value, str) else None,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
    )
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key" if actor_id else "system",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="notification.job.replayed",
        outcome="success",
        resource_type="notification_dead_letter",
        resource_id=dead_letter.id,
        request_id=request_id,
        metadata={"created_job_ids": created_job_ids},
        commit=True,
        best_effort=True,
    )
    return {
        "dead_letter_id": dead_letter.id,
        "original_job_id": dead_letter.job_id,
        "created_job_ids": created_job_ids,
    }


async def retry_notification_job_now(
    *,
    session: AsyncSession,
    tenant_id: str,
    job_id: str,
) -> NotificationJob | None:
    # Allow operators to force immediate retries while preserving attempt history and idempotent state machine rules.
    if await _is_notification_delivery_paused():
        raise RuntimeError("Notification delivery is paused by kill.notifications")
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
            NotificationJob.status.in_(["dead_lettered", "failed", "gave_up"]),
            NotificationJob.updated_at >= (_utc_now() - timedelta(hours=1)),
        )
    )
    dead_lettered = await session.scalar(
        select(func.count())
        .select_from(NotificationJob)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationJob.status == "dead_lettered",
        )
    )
    return {
        "queued": int(queued or 0),
        "failed_last_hour": int(failed_last_hour or 0),
        "dead_lettered": int(dead_lettered or 0),
    }
