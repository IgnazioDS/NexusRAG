from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Document
from nexusrag.services.ingest import queue as ingest_queue
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.entitlements import FEATURE_OPS_ADMIN, require_feature
from nexusrag.services.resilience import get_circuit_breaker_state
from nexusrag.services.telemetry import (
    availability,
    counters_snapshot,
    external_latency_by_integration,
    p95_latency,
    request_latency_by_class,
    stream_duration_stats,
)


router = APIRouter(prefix="/ops", tags=["ops"], responses=DEFAULT_ERROR_RESPONSES)


def _utc_now() -> datetime:
    # Use UTC timestamps for consistent health/ops responses across hosts.
    return datetime.now(timezone.utc)


def _percentile(values: list[float], percentile: float) -> float | None:
    # Use a stable percentile implementation to avoid external dependencies.
    if not values:
        return None
    values_sorted = sorted(values)
    rank = math.ceil(percentile / 100.0 * len(values_sorted)) - 1
    index = min(max(rank, 0), len(values_sorted) - 1)
    return float(values_sorted[index])


def _normalize_failure_reason(reason: str | None) -> str:
    # Map failure strings into stable codes for operator-friendly aggregates.
    if not reason:
        return "UNKNOWN"
    normalized = reason.strip()
    if normalized.startswith("INGEST_") or normalized.endswith("_ERROR"):
        return normalized
    if "chunk_overlap_chars" in normalized or "chunk_size_chars" in normalized:
        return "INGEST_VALIDATION_ERROR"
    if "Stored document text is missing" in normalized:
        return "INGEST_SOURCE_MISSING"
    if "queue unavailable" in normalized.lower():
        return "QUEUE_ERROR"
    if "database" in normalized.lower():
        return "DB_ERROR"
    if "Embedding dimension mismatch" in normalized:
        return "EMBEDDING_DIMENSION_MISMATCH"
    return normalized


def _db_error(message: str) -> HTTPException:
    # Keep ops errors explicit without leaking stack traces.
    return HTTPException(status_code=500, detail={"code": "DB_ERROR", "message": message})


async def _check_db_health(db: AsyncSession) -> bool:
    # Keep the DB check lightweight to avoid introducing new load.
    try:
        await db.execute(select(1))
        return True
    except SQLAlchemyError:
        return False


async def _get_queue_depth() -> int | None:
    # Degrade gracefully when Redis is unavailable.
    return await ingest_queue.get_queue_depth()


async def _get_worker_heartbeat() -> datetime | None:
    # Use the heartbeat timestamp for worker health reporting.
    return await ingest_queue.get_worker_heartbeat()


# Allow legacy unwrapped responses; v1 middleware wraps envelopes.
@router.get("/health", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def ops_health(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    # Require admin role for operational visibility endpoints.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    settings = get_settings()
    now = _utc_now()
    db_ok = await _check_db_health(db)

    queue_depth = await _get_queue_depth()
    redis_ok = queue_depth is not None

    heartbeat = await _get_worker_heartbeat() if redis_ok else None
    heartbeat_age_s = (now - heartbeat).total_seconds() if heartbeat else None

    stale_threshold = settings.worker_heartbeat_stale_after_s
    heartbeat_stale = heartbeat_age_s is None or heartbeat_age_s > stale_threshold

    status = "ok" if db_ok and redis_ok and not heartbeat_stale else "degraded"

    payload = {
        "status": status,
        "api": "ok",
        "db": "ok" if db_ok else "degraded",
        "redis": "ok" if redis_ok else "degraded",
        "worker_heartbeat_age_s": heartbeat_age_s,
        "queue_depth": queue_depth,
        "timestamp": now.isoformat(),
    }
    request_ctx = get_request_context(request)
    # Record ops views for administrative investigations.
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="ops.viewed",
        outcome="success",
        resource_type="ops",
        resource_id="health",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"path": request.url.path},
        commit=True,
        best_effort=True,
    )
    return payload


@router.get("/ingestion", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def ops_ingestion(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    # Require admin role for operational visibility endpoints.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    # Bound the window to keep ops queries predictable.
    now = _utc_now()
    window_start = now - timedelta(hours=hours)

    try:
        queued_count = await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.status == "queued", Document.queued_at >= window_start)
        )
        processing_count = await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.status == "processing",
                Document.processing_started_at >= window_start,
            )
        )
        succeeded_count = await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.status == "succeeded",
                Document.completed_at >= window_start,
            )
        )
        failed_count = await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.status == "failed", Document.completed_at >= window_start)
        )
    except SQLAlchemyError as exc:
        raise _db_error("Database error while aggregating ingestion status") from exc

    duration_rows = []
    try:
        duration_rows = (
            await db.execute(
                select(Document.processing_started_at, Document.completed_at)
                .where(
                    Document.completed_at.is_not(None),
                    Document.processing_started_at.is_not(None),
                    Document.completed_at >= window_start,
                )
                .order_by(Document.completed_at)
            )
        ).all()
    except SQLAlchemyError as exc:
        raise _db_error("Database error while aggregating ingestion durations") from exc

    durations_ms: list[float] = []
    for started_at, completed_at in duration_rows:
        duration_ms = (completed_at - started_at).total_seconds() * 1000.0
        durations_ms.append(duration_ms)

    failure_rows = []
    try:
        failure_rows = (
            await db.execute(
                select(Document.failure_reason)
                .where(Document.status == "failed", Document.completed_at >= window_start)
                .order_by(Document.completed_at.desc())
            )
        ).all()
    except SQLAlchemyError as exc:
        raise _db_error("Database error while aggregating ingestion failures") from exc

    failure_counts = Counter(_normalize_failure_reason(reason) for (reason,) in failure_rows)
    top_failure_reasons = [
        {"reason": reason, "count": count}
        for reason, count in failure_counts.most_common(5)
    ]

    queue_depth = await _get_queue_depth()
    worker_last_seen = await _get_worker_heartbeat()

    payload = {
        "window_hours": hours,
        "documents": {
            "queued": int(queued_count or 0),
            "processing": int(processing_count or 0),
            "succeeded": int(succeeded_count or 0),
            "failed": int(failed_count or 0),
        },
        "durations_ms": {
            "p50": _percentile(durations_ms, 50),
            "p95": _percentile(durations_ms, 95),
            "max": max(durations_ms) if durations_ms else None,
        },
        "top_failure_reasons": top_failure_reasons,
        "queue_depth": queue_depth,
        "worker_last_seen_at": worker_last_seen.isoformat() if worker_last_seen else None,
    }
    request_ctx = get_request_context(request)
    # Record ops views for administrative investigations.
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="ops.viewed",
        outcome="success",
        resource_type="ops",
        resource_id="ingestion",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"path": request.url.path, "window_hours": hours},
        commit=True,
        best_effort=True,
    )
    return payload


@router.get("/metrics", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def ops_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    # Require admin role for operational visibility endpoints.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    # Provide JSON metrics for dashboards when Prometheus scraping is unavailable.
    queue_depth = await _get_queue_depth()

    try:
        enqueued_total = await db.scalar(
            select(func.count()).select_from(Document).where(Document.queued_at.is_not(None))
        )
        succeeded_total = await db.scalar(
            select(func.count()).select_from(Document).where(Document.status == "succeeded")
        )
        failed_total = await db.scalar(
            select(func.count()).select_from(Document).where(Document.status == "failed")
        )
        inflight_total = await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.status.in_(["queued", "processing"]))
        )
    except SQLAlchemyError as exc:
        raise _db_error("Database error while aggregating ingestion metrics") from exc

    payload = {
        "counters": {
            "nexusrag_ingest_enqueued_total": int(enqueued_total or 0),
            "nexusrag_ingest_succeeded_total": int(succeeded_total or 0),
            "nexusrag_ingest_failed_total": int(failed_total or 0),
        },
        "gauges": {
            "nexusrag_ingest_inflight": int(inflight_total or 0),
            "nexusrag_ingest_queue_depth": queue_depth,
        },
    }
    metrics_counters = counters_snapshot()
    payload["counters"].update(
        {
            "nexusrag_service_busy_total": metrics_counters.get("service_busy_total", 0),
            "nexusrag_quota_exceeded_total": metrics_counters.get("quota_exceeded_total", 0),
            "nexusrag_rate_limited_total": metrics_counters.get("rate_limited_total", 0),
        }
    )
    payload["latency_ms"] = request_latency_by_class(3600)
    payload["external_call_latency_ms"] = external_latency_by_integration(3600)
    payload["sse_stream_duration_ms"] = stream_duration_stats()
    payload["circuit_breaker_state"] = {
        "retrieval.aws_bedrock": await get_circuit_breaker_state("retrieval.aws_bedrock"),
        "retrieval.gcp_vertex": await get_circuit_breaker_state("retrieval.gcp_vertex"),
        "tts.openai": await get_circuit_breaker_state("tts.openai"),
        "billing.webhook": await get_circuit_breaker_state("billing.webhook"),
    }
    request_ctx = get_request_context(request)
    # Record ops views for administrative investigations.
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="ops.viewed",
        outcome="success",
        resource_type="ops",
        resource_id="metrics",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"path": request.url.path},
        commit=True,
        best_effort=True,
    )
    return payload


@router.get("/slo", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def ops_slo(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Expose SLO status with availability and latency indicators.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    settings = get_settings()
    availability_5m = availability(300)
    availability_1h = availability(3600)
    if availability_1h is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "SLO_DATA_UNAVAILABLE", "message": "Insufficient SLO data"},
        )
    target = settings.slo_availability_target
    budget = max(0.1, 100.0 - target)
    error_rate_1h = 100.0 - availability_1h
    remaining_pct = max(0.0, (budget - error_rate_1h) / budget * 100.0)
    burn_rate_5m = None
    if availability_5m is not None:
        burn_rate_5m = (100.0 - availability_5m) / budget
    status = "healthy"
    if availability_1h < target:
        status = "breached"
    elif burn_rate_5m is not None and burn_rate_5m > 1.0:
        status = "at_risk"

    payload = {
        "window": "1h",
        "availability": availability_1h,
        "availability_5m": availability_5m,
        "p95": {
            "run": p95_latency(300, path_prefix="/v1/run"),
            "api": p95_latency(300, path_prefix="/v1/ui/bootstrap"),
            "documents_text": p95_latency(300, path_prefix="/v1/documents/text"),
        },
        "error_budget": {"remaining_pct": remaining_pct, "burn_rate_5m": burn_rate_5m},
        "status": status,
    }

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="ops.viewed",
        outcome="success",
        resource_type="ops",
        resource_id="slo",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"path": request.url.path},
        commit=True,
        best_effort=True,
    )
    return payload
