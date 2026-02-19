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
from nexusrag.domain.models import (
    NotificationAttempt,
    NotificationDeadLetter,
    NotificationDelivery,
    NotificationDestination,
    NotificationJob,
    NotificationRoute,
)
from nexusrag.services.audit import record_event, sanitize_metadata
from nexusrag.services.entitlements import FEATURE_OPS_ADMIN, get_effective_entitlements
from nexusrag.services.notifications.routing import resolve_destinations
from nexusrag.services.notifications.receiver_contract import (
    compute_signature,
    payload_sha256,
)
from nexusrag.services.rollouts import resolve_kill_switch
from nexusrag.services.security.keyring import decrypt_keyring_secret, encrypt_keyring_secret

_READY_DELIVERY_STATUSES = ("queued", "retrying")
_notification_queue_pool = None
_notification_queue_pool_loop = None
_notification_queue_lock = asyncio.Lock()
_RESERVED_NOTIFICATION_HEADERS = {
    "x-notification-id",
    "x-notification-delivery-id",
    "x-notification-destination-id",
    "x-notification-attempt",
    "x-notification-event-type",
    "x-notification-tenant-id",
    "x-notification-signature",
    "x-notification-payload-sha256",
}

_DELIVERY_TERMINAL_STATUSES = {"delivered", "skipped", "dlq"}
_NON_TERMINAL_HTTP_4XX = {408, 429}


def _utc_now() -> datetime:
    # Keep notification scheduling and retry bookkeeping in UTC for deterministic comparisons.
    return datetime.now(timezone.utc)


def _validate_destination_url(destination_url: str) -> str:
    # Restrict destinations to explicit URL schemes so notification routing never accepts ambiguous targets.
    normalized = destination_url.strip()
    if normalized.startswith(("http://", "https://", "noop://")):
        return normalized
    raise ValueError("destination_url must start with http://, https://, or noop://")


def _normalize_destination_headers(headers_json: dict[str, Any] | None) -> dict[str, str]:
    # Normalize destination headers and block reserved notification contract headers from being overridden.
    if headers_json is None:
        return {}
    if not isinstance(headers_json, dict):
        raise ValueError("headers_json must be an object")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in headers_json.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if not key:
            raise ValueError("headers_json keys must be non-empty")
        if key.lower() in _RESERVED_NOTIFICATION_HEADERS:
            raise ValueError(f"headers_json key '{key}' is reserved")
        normalized[key] = value
    return normalized


def _serialize_payload(payload_json: dict[str, Any]) -> bytes:
    # Serialize payloads deterministically so hashing/signing and receiver verification stay stable across retries.
    return json.dumps(payload_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _payload_sha256(payload_bytes: bytes) -> str:
    # Persist attempt-level hashes so operators can prove exactly which bytes were sent to receivers.
    return payload_sha256(payload_bytes)


def _sign_payload(*, secret: str, payload_bytes: bytes) -> str:
    # Sign payload bytes with the canonical receiver contract helper so algorithm changes stay centralized.
    return compute_signature(payload_bytes, secret)


def _destination_token(*, destination_id: str | None, destination_url: str) -> str:
    # Build stable per-destination identifiers even when destination rows are deleted after enqueue time.
    if destination_id:
        return destination_id
    return f"global:{hashlib.sha256(destination_url.encode('utf-8')).hexdigest()[:20]}"


def _delivery_key(*, job_id: str, destination_token: str) -> str:
    # Keep delivery keys deterministic so receiver-side idempotency can key on stable sender identifiers.
    digest = hashlib.sha256(f"{job_id}:{destination_token}".encode("utf-8")).hexdigest()
    return f"delivery:{digest[:24]}"


async def _sync_job_status_from_deliveries(*, session: AsyncSession, job_id: str) -> NotificationJob | None:
    # Derive job status from delivery rows so job-level APIs remain backward compatible with fanout semantics.
    job = await session.get(NotificationJob, job_id)
    if job is None:
        return None
    deliveries = (
        await session.execute(
            select(NotificationDelivery).where(NotificationDelivery.job_id == job_id)
        )
    ).scalars().all()
    if not deliveries:
        return job
    statuses = {row.status for row in deliveries}
    attempt_count = max(int(row.attempt_count or 0) for row in deliveries)
    next_attempt = min((row.next_attempt_at for row in deliveries if row.next_attempt_at), default=job.next_attempt_at)
    last_error = next((row.last_error for row in deliveries if row.last_error), None)
    if statuses <= {"delivered", "skipped"}:
        derived_status = "delivered"
    elif statuses <= _DELIVERY_TERMINAL_STATUSES and "dlq" in statuses:
        derived_status = "dlq"
    elif "delivering" in statuses:
        derived_status = "delivering"
    elif "retrying" in statuses:
        derived_status = "retrying"
    else:
        derived_status = "queued"
    job.status = derived_status
    job.attempt_count = attempt_count
    job.next_attempt_at = next_attempt
    job.last_error = last_error
    await session.flush()
    return job


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
    headers_json: dict[str, Any] | None = None,
    secret: str | None = None,
) -> NotificationDestination:
    # Enforce canonical URL validation and uniqueness for deterministic destination routing.
    normalized_headers = _normalize_destination_headers(headers_json)
    row = NotificationDestination(
        id=uuid4().hex,
        tenant_id=tenant_id,
        destination_url=_validate_destination_url(destination_url),
        secret_encrypted=encrypt_keyring_secret(secret) if secret else None,
        headers_json=normalized_headers,
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
    enabled: bool | None,
    headers_json: dict[str, Any] | None = None,
    secret: str | None = None,
) -> NotificationDestination | None:
    # Apply enable/disable toggles in place so destination identifiers remain stable for operators.
    row = await session.get(NotificationDestination, destination_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    if enabled is not None:
        row.enabled = bool(enabled)
    if headers_json is not None:
        row.headers_json = _normalize_destination_headers(headers_json)
    if secret is not None:
        # Replace destination secret atomically so rotation can happen without secret reads.
        row.secret_encrypted = encrypt_keyring_secret(secret)
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


async def enqueue_notification_delivery(*, delivery_id: str, defer_ms: int = 0) -> bool:
    # Publish delivery ids onto ARQ so fanout destinations are processed independently.
    settings = get_settings()
    defer_delta = timedelta(milliseconds=max(0, int(defer_ms)))
    try:
        redis = await get_notification_queue_pool()
        await redis.enqueue_job(
            "deliver_notification_delivery",
            delivery_id,
            _queue_name=settings.notify_queue_name,
            _defer_by=defer_delta if defer_delta.total_seconds() > 0 else None,
        )
        return True
    except Exception:  # noqa: BLE001 - keep enqueue best-effort and rely on due-job requeue fallback.
        return False


async def enqueue_notification_job(*, job_id: str, defer_ms: int = 0) -> bool:
    # Preserve compatibility for call sites that enqueue by logical job id.
    # Invariant: all ready deliveries for the job are enqueued; a false return means none were queued.
    queued_any = False
    # Avoid creating nested session management helpers by resolving deliveries in a short-lived session.
    from nexusrag.persistence.db import SessionLocal

    async with SessionLocal() as local_session:
        delivery_ids = (
            await local_session.execute(
                select(NotificationDelivery.id).where(
                    NotificationDelivery.job_id == job_id,
                    NotificationDelivery.status.in_(_READY_DELIVERY_STATUSES),
                )
            )
        ).scalars().all()
    for delivery_id in delivery_ids:
        if await enqueue_notification_delivery(delivery_id=str(delivery_id), defer_ms=defer_ms):
            queued_any = True
    return queued_any


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


def _response_error_reason(response: httpx.Response) -> str:
    # Parse explicit receiver reasons first so terminal classification can distinguish invalid signatures.
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        reason = payload.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip().lower()
    return f"http_{int(response.status_code)}"


def _classify_delivery_error(
    *,
    exc: Exception,
) -> tuple[bool, str]:
    # Classify delivery outcomes deterministically so retries and DLQ behavior are policy-driven.
    settings = get_settings()
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = int(exc.response.status_code)
        reason = _response_error_reason(exc.response)
        if reason == "secret_missing" and settings.notify_terminal_misconfig:
            return True, "misconfiguration"
        if status_code == 401 and "signature" in reason and settings.notify_terminal_invalid_signature:
            return True, "invalid_signature"
        if 400 <= status_code < 500 and status_code not in _NON_TERMINAL_HTTP_4XX:
            if settings.notify_terminal_4xx:
                return True, "permanent"
        return False, reason
    return False, "retryable_failure"


async def _dead_letter_job(
    *,
    session: AsyncSession,
    job: NotificationJob,
    delivery: NotificationDelivery | None,
    reason: str,
    last_error: str | None,
) -> NotificationDeadLetter:
    # Persist a redacted DLQ payload so replay/debug flows never rely on raw sensitive webhook content.
    payload = sanitize_metadata(job.payload_json or {})
    row = NotificationDeadLetter(
        id=uuid4().hex,
        tenant_id=job.tenant_id,
        job_id=job.id,
        delivery_id=delivery.id if delivery is not None else None,
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
    # Create one logical job with per-destination delivery rows so fanout retries stay isolated.
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
    settings = get_settings()
    fanout_limit = max(1, int(settings.notify_delivery_fanout_max))
    if len(destinations) > fanout_limit:
        destinations = list(destinations[:fanout_limit])

    now = _utc_now()
    window_start = dedupe_window_start(now=now, window_seconds=get_settings().notify_dedupe_window_s)
    incident_id = payload.get("incident_id")
    if not isinstance(incident_id, str):
        incident_id = None
    alert_event_id = payload.get("alert_event_id")
    if not isinstance(alert_event_id, str):
        alert_event_id = None
    dedupe_key = str(payload.get("dedupe_key") or event_type)
    job = NotificationJob(
        id=uuid4().hex,
        tenant_id=tenant_id,
        incident_id=incident_id,
        alert_event_id=alert_event_id,
        # Keep a representative destination for backward-compatible job payloads while deliveries hold canonical fanout state.
        destination=destinations[0].destination_url,
        dedupe_key=dedupe_key,
        dedupe_window_start=window_start,
        payload_json={
            "event_type": event_type,
            "severity": severity,
            "source": source,
            "category": category,
            "tenant_id": tenant_id,
            "payload": payload,
            "fanout_count": len(destinations),
        },
        status="queued",
        next_attempt_at=now,
        attempt_count=0,
        last_error=None,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError:
        # Drop duplicate jobs inside the dedupe window so repeated incident updates do not create duplicate fanout sets.
        await session.rollback()
        return []

    created_delivery_ids: list[str] = []
    for resolved in destinations:
        destination_token = _destination_token(
            destination_id=resolved.destination_id,
            destination_url=resolved.destination_url,
        )
        delivery = NotificationDelivery(
            id=uuid4().hex,
            job_id=job.id,
            tenant_id=tenant_id,
            destination_id=destination_token,
            destination=resolved.destination_url,
            status="queued",
            attempt_count=0,
            next_attempt_at=now,
            last_error=None,
            delivered_at=None,
            receipt_json={
                "route_id": resolved.route_id,
                "destination_source": resolved.source,
            },
            delivery_key=_delivery_key(job_id=job.id, destination_token=destination_token),
        )
        session.add(delivery)
        created_delivery_ids.append(delivery.id)

    await session.commit()

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
            "event_type": event_type,
            "dedupe_key": dedupe_key,
            "fanout_count": len(created_delivery_ids),
            "delivery_ids": created_delivery_ids,
        },
        commit=True,
        best_effort=True,
    )
    for delivery_id in created_delivery_ids:
        enqueued = await enqueue_notification_delivery(delivery_id=delivery_id)
        if enqueued:
            continue
        # Record enqueue degradation so operators can distinguish queue transport issues from receiver failures.
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="notification.job.enqueue_degraded",
            outcome="failure",
            resource_type="notification_delivery",
            resource_id=delivery_id,
            request_id=request_id,
            metadata={"event_type": event_type},
            commit=True,
            best_effort=True,
        )
    return [job.id]


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
    # Re-enqueue overdue deliveries to recover from transient worker outages without losing durable state.
    if await _is_notification_delivery_paused():
        return 0
    now = _utc_now()
    stale_cutoff = now - timedelta(seconds=max(1, int(get_settings().notify_worker_poll_interval_s)))
    rows = (
        await session.execute(
            select(NotificationDelivery.id)
            .where(
                NotificationDelivery.status.in_(_READY_DELIVERY_STATUSES),
                NotificationDelivery.next_attempt_at <= now,
                NotificationDelivery.updated_at <= stale_cutoff,
            )
            .order_by(NotificationDelivery.next_attempt_at.asc(), NotificationDelivery.created_at.asc())
            .limit(max(1, limit))
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    delivery_ids = [str(row) for row in rows]
    if not delivery_ids:
        return 0
    await session.execute(
        update(NotificationDelivery)
        .where(NotificationDelivery.id.in_(delivery_ids))
        .values(updated_at=now)
    )
    await session.commit()
    count = 0
    for delivery_id in delivery_ids:
        if await enqueue_notification_delivery(delivery_id=delivery_id):
            count += 1
    return count


async def _resolve_destination_delivery_contract(
    *,
    session: AsyncSession,
    delivery: NotificationDelivery,
) -> tuple[dict[str, str], str | None]:
    # Resolve destination headers and secret lazily so retries always use latest destination configuration.
    destination_id = delivery.destination_id
    if not destination_id or destination_id.startswith("global:"):
        return {}, None
    row = await session.get(NotificationDestination, destination_id)
    if row is None or row.tenant_id != delivery.tenant_id:
        return {}, None
    headers_json = row.headers_json if isinstance(row.headers_json, dict) else {}
    headers = _normalize_destination_headers(headers_json)
    if not row.secret_encrypted:
        return headers, None
    try:
        return headers, decrypt_keyring_secret(row.secret_encrypted)
    except Exception:  # noqa: BLE001 - treat undecryptable secrets as unavailable and continue unsigned delivery.
        return headers, None


async def _deliver(*, destination: str, payload_bytes: bytes, headers: dict[str, str]) -> dict[str, Any]:
    # Keep delivery adapters small and deterministic: noop for local/dev, webhook for live integrations.
    if destination.startswith("noop://"):
        return {"status_code": 200, "headers": {}, "body_preview": ""}
    timeout_s = max(0.2, get_settings().ext_call_timeout_ms / 1000.0)
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            destination,
            content=payload_bytes,
            headers=headers,
        )
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Receiver rejected notification delivery ({response.status_code})",
                request=response.request,
                response=response,
            )
        return {
            "status_code": int(response.status_code),
            "headers": {str(k): str(v) for k, v in response.headers.items()},
            "body_preview": response.text[:512] if response.text else "",
        }


async def _claim_notification_delivery(*, session: AsyncSession, delivery_id: str) -> NotificationDelivery | None:
    # Claim with row-level locking so only one worker transitions a ready delivery into delivering at a time.
    now = _utc_now()
    row = (
        await session.execute(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.status.in_(_READY_DELIVERY_STATUSES),
                NotificationDelivery.next_attempt_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if row is None:
        await session.rollback()
        return None
    row.status = "delivering"
    row.updated_at = now
    await session.commit()
    await session.refresh(row)
    return row


async def process_notification_delivery(*, session: AsyncSession, delivery_id: str) -> NotificationDelivery | None:
    # Execute one destination delivery attempt and persist immutable attempt history for forensics.
    if await _is_notification_delivery_paused():
        # Keep deliveries queued when paused so operators can resume without losing durable records.
        return None
    delivery = await _claim_notification_delivery(session=session, delivery_id=delivery_id)
    if delivery is None:
        return None
    job = await session.get(NotificationJob, delivery.job_id)
    if job is None:
        await session.rollback()
        return None
    await record_event(
        session=session,
        tenant_id=delivery.tenant_id,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="notification.job.claimed",
        outcome="success",
        resource_type="notification_delivery",
        resource_id=delivery.id,
        request_id=None,
        metadata={"status": delivery.status, "job_id": job.id},
        commit=True,
        best_effort=True,
    )
    now = _utc_now()
    max_age_seconds = max(1, int(get_settings().notify_max_age_seconds))
    if (now - job.created_at).total_seconds() > max_age_seconds:
        # Expire stale deliveries deterministically to prevent infinite retries on old incidents.
        delivery.status = "dlq"
        delivery.next_attempt_at = now
        delivery.last_error = "expired"
        await _dead_letter_job(
            session=session,
            job=job,
            delivery=delivery,
            reason="expired",
            last_error="Notification exceeded max age before delivery",
        )
        await _sync_job_status_from_deliveries(session=session, job_id=job.id)
        await session.commit()
        await session.refresh(delivery)
        await record_event(
            session=session,
            tenant_id=delivery.tenant_id,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type="notification.job.dlq",
            outcome="failure",
            resource_type="notification_delivery",
            resource_id=delivery.id,
            request_id=None,
            metadata={"reason": "expired", "max_age_seconds": max_age_seconds, "job_id": job.id},
            commit=True,
            best_effort=True,
        )
        return delivery
    payload_json = job.payload_json if isinstance(job.payload_json, dict) else {}
    payload_bytes = _serialize_payload(payload_json)
    payload_sha = _payload_sha256(payload_bytes)
    event_type = str(payload_json.get("event_type") or "unknown")
    destination_headers, signing_secret = await _resolve_destination_delivery_contract(session=session, delivery=delivery)
    attempt_no = int(delivery.attempt_count) + 1
    global_attempt_no = int(
        (
            await session.scalar(
                select(func.coalesce(func.max(NotificationAttempt.attempt_no), 0)).where(
                    NotificationAttempt.job_id == job.id
                )
            )
        )
        or 0
    ) + 1
    attempt = NotificationAttempt(
        job_id=job.id,
        delivery_id=delivery.id,
        attempt_no=global_attempt_no,
        started_at=now,
        finished_at=None,
        payload_sha256=payload_sha,
        outcome="running",
        error=None,
    )
    session.add(attempt)
    await session.flush()
    request_headers = dict(destination_headers)
    request_headers.update(
        {
            "Content-Type": "application/json",
            "X-Notification-Id": job.id,
            "X-Notification-Delivery-Id": delivery.id,
            "X-Notification-Destination-Id": delivery.destination_id,
            "X-Notification-Attempt": str(attempt_no),
            "X-Notification-Event-Type": event_type,
            "X-Notification-Tenant-Id": job.tenant_id,
            "X-Notification-Payload-Sha256": payload_sha,
        }
    )
    signature_missing = signing_secret is None
    if signing_secret:
        request_headers["X-Notification-Signature"] = _sign_payload(secret=signing_secret, payload_bytes=payload_bytes)

    try:
        receipt = await _deliver(destination=delivery.destination, payload_bytes=payload_bytes, headers=request_headers)
    except Exception as exc:  # noqa: BLE001 - delivery failures are isolated to job state updates.
        attempt.finished_at = _utc_now()
        attempt.outcome = "failure"
        attempt.error = str(exc)
        delivery.attempt_count = attempt_no
        delivery.last_error = str(exc)
        max_attempts = max(1, int(get_settings().notify_max_attempts))
        non_retriable, reason = _classify_delivery_error(exc=exc)
        if non_retriable or attempt_no >= max_attempts:
            delivery.status = "dlq"
            delivery.next_attempt_at = attempt.finished_at
            await _dead_letter_job(
                session=session,
                job=job,
                delivery=delivery,
                reason=reason if non_retriable else "max_attempts_exceeded",
                last_error=str(exc),
            )
            event_type = "notification.job.dlq"
        else:
            delay_ms = retry_backoff_ms(job_id=delivery.id, attempt_no=attempt_no)
            delivery.status = "retrying"
            delivery.next_attempt_at = attempt.finished_at + timedelta(milliseconds=delay_ms)
            event_type = "notification.job.retry_scheduled"
        await _sync_job_status_from_deliveries(session=session, job_id=job.id)
        await session.commit()
        await session.refresh(delivery)
        if delivery.status == "retrying":
            await enqueue_notification_delivery(
                delivery_id=delivery.id,
                defer_ms=retry_backoff_ms(job_id=delivery.id, attempt_no=attempt_no),
            )
        await record_event(
            session=session,
            tenant_id=delivery.tenant_id,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type=event_type,
            outcome="failure",
            resource_type="notification_delivery",
            resource_id=delivery.id,
            request_id=None,
            metadata={
                "attempt_no": attempt_no,
                "destination": delivery.destination,
                "status": delivery.status,
                "job_id": job.id,
                "payload_sha256": payload_sha,
            },
            commit=True,
            best_effort=True,
        )
        if signature_missing:
            await record_event(
                session=session,
                tenant_id=job.tenant_id,
                actor_type="system",
                actor_id=None,
                actor_role=None,
                event_type="notification.signature.missing",
                outcome="failure",
                resource_type="notification_delivery",
                resource_id=delivery.id,
                request_id=None,
                metadata={"attempt_no": attempt_no, "destination": delivery.destination, "job_id": job.id},
                commit=True,
                best_effort=True,
            )
        if delivery.status == "dlq":
            await record_event(
                session=session,
                tenant_id=delivery.tenant_id,
                actor_type="system",
                actor_id=None,
                actor_role=None,
                event_type="notification.job.dlq",
                outcome="failure",
                resource_type="notification_delivery",
                resource_id=delivery.id,
                request_id=None,
                metadata={"attempt_no": attempt_no, "destination": delivery.destination, "job_id": job.id},
                commit=True,
                best_effort=True,
            )
        return delivery

    attempt.finished_at = _utc_now()
    attempt.outcome = "success"
    delivery.attempt_count = attempt_no
    delivery.last_error = None
    delivery.status = "delivered"
    delivery.delivered_at = attempt.finished_at
    delivery.next_attempt_at = attempt.finished_at
    receipt_headers = receipt.get("headers") if isinstance(receipt, dict) else {}
    delivery.receipt_json = {
        "status_code": int(receipt.get("status_code", 200)) if isinstance(receipt, dict) else 200,
        "headers": {
            "x-notification-id": str(receipt_headers.get("x-notification-id") or ""),
            "x-notification-receipt": str(receipt_headers.get("x-notification-receipt") or ""),
        },
        "body_preview": str(receipt.get("body_preview") or "") if isinstance(receipt, dict) else "",
    }
    await _sync_job_status_from_deliveries(session=session, job_id=job.id)
    await session.commit()
    await session.refresh(delivery)
    await record_event(
        session=session,
        tenant_id=delivery.tenant_id,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="notification.job.delivered",
        outcome="success",
        resource_type="notification_delivery",
        resource_id=delivery.id,
        request_id=None,
        metadata={
            "attempt_no": attempt_no,
            "destination": delivery.destination,
            "payload_sha256": payload_sha,
            "job_id": job.id,
        },
        commit=True,
        best_effort=True,
    )
    if signature_missing:
        await record_event(
            session=session,
            tenant_id=delivery.tenant_id,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type="notification.signature.missing",
            outcome="failure",
            resource_type="notification_delivery",
            resource_id=delivery.id,
            request_id=None,
            metadata={"attempt_no": attempt_no, "destination": delivery.destination, "job_id": job.id},
            commit=True,
            best_effort=True,
        )
    return delivery


async def process_notification_job(*, session: AsyncSession, job_id: str) -> NotificationJob | None:
    # Preserve compatibility by processing one due delivery for a job and returning the synced parent job row.
    delivery = (
        await session.execute(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.job_id == job_id,
                NotificationDelivery.status.in_(_READY_DELIVERY_STATUSES),
                NotificationDelivery.next_attempt_at <= _utc_now(),
            )
            .order_by(NotificationDelivery.next_attempt_at.asc(), NotificationDelivery.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if delivery is None:
        await _sync_job_status_from_deliveries(session=session, job_id=job_id)
        return None
    processed = await process_notification_delivery(session=session, delivery_id=delivery.id)
    if processed is None:
        return None
    return await _sync_job_status_from_deliveries(session=session, job_id=job_id)


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


async def list_notification_deliveries(
    *,
    session: AsyncSession,
    tenant_id: str,
    status_filter: str | None = None,
    job_id: str | None = None,
    destination_id: str | None = None,
    limit: int = 100,
) -> list[NotificationDelivery]:
    # Expose tenant-scoped delivery rows so operators can triage fanout outcomes per destination.
    query = select(NotificationDelivery).where(NotificationDelivery.tenant_id == tenant_id)
    if status_filter:
        query = query.where(NotificationDelivery.status == status_filter)
    if job_id:
        query = query.where(NotificationDelivery.job_id == job_id)
    if destination_id:
        query = query.where(NotificationDelivery.destination_id == destination_id)
    rows = (
        await session.execute(
            query.order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc()).limit(
                max(1, min(limit, 500))
            )
        )
    ).scalars().all()
    return list(rows)


async def get_notification_delivery(
    *,
    session: AsyncSession,
    tenant_id: str,
    delivery_id: str,
) -> NotificationDelivery | None:
    # Enforce tenant ownership before returning destination-specific delivery state.
    row = await session.get(NotificationDelivery, delivery_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


async def list_notification_attempts(
    *,
    session: AsyncSession,
    tenant_id: str,
    job_id: str,
) -> list[NotificationAttempt] | None:
    # Return immutable attempt history only for tenant-owned jobs to preserve isolation boundaries.
    job = await session.get(NotificationJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        return None
    rows = (
        await session.execute(
            select(NotificationAttempt)
            .where(NotificationAttempt.job_id == job_id)
            .order_by(NotificationAttempt.attempt_no.asc(), NotificationAttempt.started_at.asc())
        )
    ).scalars().all()
    return list(rows)


async def list_notification_delivery_attempts(
    *,
    session: AsyncSession,
    tenant_id: str,
    delivery_id: str,
) -> list[NotificationAttempt] | None:
    # Return immutable attempt history for one delivery while enforcing tenant ownership.
    delivery = await session.get(NotificationDelivery, delivery_id)
    if delivery is None or delivery.tenant_id != tenant_id:
        return None
    rows = (
        await session.execute(
            select(NotificationAttempt)
            .where(NotificationAttempt.delivery_id == delivery_id)
            .order_by(NotificationAttempt.started_at.asc(), NotificationAttempt.id.asc())
        )
    ).scalars().all()
    return list(rows)


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


async def replay_notification_delivery(
    *,
    session: AsyncSession,
    tenant_id: str,
    delivery_id: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> dict[str, str] | None:
    # Replay one dead-lettered delivery as a new logical job+delivery pair to preserve immutable history.
    delivery = await get_notification_delivery(session=session, tenant_id=tenant_id, delivery_id=delivery_id)
    if delivery is None:
        return None
    if delivery.status != "dlq":
        raise ValueError("Only dead-lettered deliveries can be replayed")
    parent_job = await session.get(NotificationJob, delivery.job_id)
    if parent_job is None:
        return None
    now = _utc_now()
    replay_job = NotificationJob(
        id=uuid4().hex,
        tenant_id=tenant_id,
        incident_id=parent_job.incident_id,
        alert_event_id=parent_job.alert_event_id,
        destination=delivery.destination,
        dedupe_key=f"delivery-replay:{delivery.id}:{uuid4().hex[:8]}",
        dedupe_window_start=dedupe_window_start(now=now, window_seconds=get_settings().notify_dedupe_window_s),
        payload_json={
            **(parent_job.payload_json or {}),
            "replayed_from_job_id": parent_job.id,
            "replayed_from_delivery_id": delivery.id,
        },
        status="queued",
        next_attempt_at=now,
        attempt_count=0,
        last_error=None,
    )
    replay_delivery = NotificationDelivery(
        id=uuid4().hex,
        job_id=replay_job.id,
        tenant_id=tenant_id,
        destination_id=delivery.destination_id,
        destination=delivery.destination,
        status="queued",
        attempt_count=0,
        next_attempt_at=now,
        last_error=None,
        delivered_at=None,
        receipt_json=None,
        delivery_key=_delivery_key(job_id=replay_job.id, destination_token=delivery.destination_id),
    )
    session.add(replay_job)
    session.add(replay_delivery)
    await session.commit()
    await enqueue_notification_delivery(delivery_id=replay_delivery.id)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key" if actor_id else "system",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="notification.job.replayed",
        outcome="success",
        resource_type="notification_delivery",
        resource_id=delivery.id,
        request_id=request_id,
        metadata={"new_job_id": replay_job.id, "new_delivery_id": replay_delivery.id},
        commit=True,
        best_effort=True,
    )
    return {"job_id": replay_job.id, "delivery_id": replay_delivery.id}


async def replay_dead_letter(
    *,
    session: AsyncSession,
    tenant_id: str,
    dead_letter_id: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> dict[str, Any] | None:
    # Replay DLQ records through delivery-aware flows while preserving tenant isolation.
    if await _is_notification_delivery_paused():
        raise RuntimeError("Notification delivery is paused by kill.notifications")
    dead_letter = await get_notification_dead_letter(
        session=session,
        tenant_id=tenant_id,
        dead_letter_id=dead_letter_id,
    )
    if dead_letter is None:
        return None
    original_delivery_id = dead_letter.delivery_id
    if isinstance(original_delivery_id, str) and original_delivery_id:
        replayed = await replay_notification_delivery(
            session=session,
            tenant_id=tenant_id,
            delivery_id=original_delivery_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
        )
        if replayed is None:
            return None
        return {
            "dead_letter_id": dead_letter.id,
            "original_job_id": dead_letter.job_id,
            "original_delivery_id": original_delivery_id,
            "created_job_ids": [replayed["job_id"]],
            "created_delivery_ids": [replayed["delivery_id"]],
        }
    dead_letter_id_value = dead_letter.id
    original_job_id = dead_letter.job_id
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
        # Force a fresh dedupe bucket key so operator-initiated replay always creates a new durable job.
        "dedupe_key": f"replay:{dead_letter.id}",
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
        resource_id=dead_letter_id_value,
        request_id=request_id,
        metadata={"created_job_ids": created_job_ids},
        commit=True,
        best_effort=True,
    )
    return {
        # Return captured identifiers to avoid ORM attribute refresh after the audit commit.
        "dead_letter_id": dead_letter_id_value,
        "original_job_id": original_job_id,
        "created_job_ids": created_job_ids,
    }


async def retry_notification_job_now(
    *,
    session: AsyncSession,
    tenant_id: str,
    job_id: str,
) -> NotificationJob | None:
    # Allow operators to force immediate retries for all retryable deliveries under a logical job.
    if await _is_notification_delivery_paused():
        raise RuntimeError("Notification delivery is paused by kill.notifications")
    row = await get_notification_job(session=session, tenant_id=tenant_id, job_id=job_id)
    if row is None:
        return None
    if row.status == "delivered":
        return row
    deliveries = (
        await session.execute(
            select(NotificationDelivery).where(NotificationDelivery.job_id == row.id)
        )
    ).scalars().all()
    if any(item.status == "delivering" for item in deliveries):
        raise ValueError("Notification job is currently delivering")
    queued_delivery_ids: list[str] = []
    now = _utc_now()
    for item in deliveries:
        if item.status == "delivered":
            continue
        if item.status == "dlq":
            raise ValueError("Notification job has dead-lettered deliveries; replay the delivery instead")
        if item.status not in _READY_DELIVERY_STATUSES:
            raise ValueError(f"Notification delivery state '{item.status}' cannot be retried now")
        item.status = "queued"
        item.next_attempt_at = now
        queued_delivery_ids.append(item.id)
    await _sync_job_status_from_deliveries(session=session, job_id=row.id)
    await session.commit()
    await session.refresh(row)
    for delivery_id in queued_delivery_ids:
        await enqueue_notification_delivery(delivery_id=delivery_id)
    return row


async def retry_notification_delivery_now(
    *,
    session: AsyncSession,
    tenant_id: str,
    delivery_id: str,
) -> NotificationDelivery | None:
    # Allow operators to force immediate retry for one delivery without affecting sibling fanout rows.
    if await _is_notification_delivery_paused():
        raise RuntimeError("Notification delivery is paused by kill.notifications")
    row = await get_notification_delivery(session=session, tenant_id=tenant_id, delivery_id=delivery_id)
    if row is None:
        return None
    if row.status == "delivered":
        return row
    if row.status == "delivering":
        raise ValueError("Notification delivery is currently delivering")
    if row.status == "dlq":
        raise ValueError("Notification delivery is dead-lettered; replay the delivery instead")
    if row.status not in _READY_DELIVERY_STATUSES:
        raise ValueError(f"Notification delivery state '{row.status}' cannot be retried now")
    row.status = "queued"
    row.next_attempt_at = _utc_now()
    await _sync_job_status_from_deliveries(session=session, job_id=row.job_id)
    await session.commit()
    await session.refresh(row)
    await enqueue_notification_delivery(delivery_id=row.id)
    return row


async def notification_queue_summary(*, session: AsyncSession, tenant_id: str) -> dict[str, Any]:
    # Expose compact queue, delivery, and attempt counters for /ops surfaces without returning payload content.
    jobs_queued = await session.scalar(
        select(func.count())
        .select_from(NotificationJob)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationJob.status == "queued",
        )
    )
    jobs_delivering = await session.scalar(
        select(func.count())
        .select_from(NotificationJob)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationJob.status == "delivering",
        )
    )
    jobs_retrying = await session.scalar(
        select(func.count())
        .select_from(NotificationJob)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationJob.status == "retrying",
        )
    )
    jobs_dlq = await session.scalar(
        select(func.count())
        .select_from(NotificationJob)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationJob.status == "dlq",
        )
    )
    deliveries_queued = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.tenant_id == tenant_id,
            NotificationDelivery.status == "queued",
        )
    )
    deliveries_delivering = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.tenant_id == tenant_id,
            NotificationDelivery.status == "delivering",
        )
    )
    deliveries_retrying = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.tenant_id == tenant_id,
            NotificationDelivery.status == "retrying",
        )
    )
    deliveries_dlq = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.tenant_id == tenant_id,
            NotificationDelivery.status == "dlq",
        )
    )
    fifteen_minutes_ago = _utc_now() - timedelta(minutes=15)
    attempts_last_15m = await session.scalar(
        select(func.count())
        .select_from(NotificationAttempt)
        .join(NotificationJob, NotificationAttempt.job_id == NotificationJob.id)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationAttempt.started_at >= fifteen_minutes_ago,
        )
    )
    failures_last_15m = await session.scalar(
        select(func.count())
        .select_from(NotificationAttempt)
        .join(NotificationJob, NotificationAttempt.job_id == NotificationJob.id)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationAttempt.started_at >= fifteen_minutes_ago,
            NotificationAttempt.outcome == "failure",
        )
    )
    jobs_failed_last_hour = await session.scalar(
        select(func.count())
        .select_from(NotificationJob)
        .where(
            NotificationJob.tenant_id == tenant_id,
            NotificationJob.status == "dlq",
            NotificationJob.updated_at >= (_utc_now() - timedelta(hours=1)),
        )
    )
    top_failure_rows = (
        await session.execute(
            select(NotificationAttempt.error, func.count(NotificationAttempt.id).label("count"))
            .select_from(NotificationAttempt)
            .join(NotificationJob, NotificationAttempt.job_id == NotificationJob.id)
            .where(
                NotificationJob.tenant_id == tenant_id,
                NotificationAttempt.started_at >= fifteen_minutes_ago,
                NotificationAttempt.outcome == "failure",
            )
            .group_by(NotificationAttempt.error)
            .order_by(func.count(NotificationAttempt.id).desc())
            .limit(5)
        )
    ).all()
    top_failure_reasons = [
        {"reason": str(reason or "unknown"), "count": int(count or 0)}
        for reason, count in top_failure_rows
    ]
    delivery_latency_rows = (
        await session.execute(
            select(
                func.extract("epoch", NotificationDelivery.delivered_at - NotificationDelivery.created_at).label("latency_seconds")
            )
            .where(
                NotificationDelivery.tenant_id == tenant_id,
                NotificationDelivery.status == "delivered",
                NotificationDelivery.delivered_at >= fifteen_minutes_ago,
            )
        )
    ).all()
    latencies_ms = sorted(
        int(float(latency_seconds) * 1000)
        for latency_seconds, in delivery_latency_rows
        if latency_seconds is not None and float(latency_seconds) >= 0
    )

    def _percentile(values: list[int], quantile: float) -> int | None:
        if not values:
            return None
        index = int(round((len(values) - 1) * quantile))
        index = max(0, min(index, len(values) - 1))
        return int(values[index])

    delivered_last_15m = await session.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.tenant_id == tenant_id,
            NotificationDelivery.status == "delivered",
            NotificationDelivery.delivered_at >= fifteen_minutes_ago,
        )
    )
    total_completed_15m = int((delivered_last_15m or 0) + (failures_last_15m or 0))
    success_rate_15m = (float(delivered_last_15m or 0) / float(total_completed_15m)) if total_completed_15m else 1.0
    return {
        "jobs_queued": int(jobs_queued or 0),
        "jobs_delivering": int(jobs_delivering or 0),
        "jobs_retrying": int(jobs_retrying or 0),
        "jobs_dlq": int(jobs_dlq or 0),
        "deliveries_queued": int(deliveries_queued or 0),
        "deliveries_delivering": int(deliveries_delivering or 0),
        "deliveries_retrying": int(deliveries_retrying or 0),
        "deliveries_dlq": int(deliveries_dlq or 0),
        "deliveries_delivered_last_15m": int(delivered_last_15m or 0),
        "jobs_failed_last_hour": int(jobs_failed_last_hour or 0),
        "attempts_last_15m": int(attempts_last_15m or 0),
        "failures_last_15m": int(failures_last_15m or 0),
        "success_rate_15m": round(success_rate_15m, 4),
        "p50_delivery_latency_ms": _percentile(latencies_ms, 0.50),
        "p95_delivery_latency_ms": _percentile(latencies_ms, 0.95),
        "top_failure_reasons": top_failure_reasons,
    }
