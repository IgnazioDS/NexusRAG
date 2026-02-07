from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Document
from nexusrag.services.ingest import queue as ingest_queue


router = APIRouter(prefix="/ops", tags=["ops"])


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


@router.get("/health")
async def ops_health(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    # Require admin role for operational visibility endpoints.
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

    return {
        "status": status,
        "api": "ok",
        "db": "ok" if db_ok else "degraded",
        "redis": "ok" if redis_ok else "degraded",
        "worker_heartbeat_age_s": heartbeat_age_s,
        "queue_depth": queue_depth,
        "timestamp": now.isoformat(),
    }


@router.get("/ingestion")
async def ops_ingestion(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    # Require admin role for operational visibility endpoints.
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

    return {
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


@router.get("/metrics")
async def ops_metrics(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict:
    # Require admin role for operational visibility endpoints.
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

    return {
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
