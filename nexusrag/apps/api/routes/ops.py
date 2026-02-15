from __future__ import annotations

import math
import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import BackupJob, Document, RestoreDrill
from nexusrag.services.ingest import queue as ingest_queue
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.backup import (
    create_backup_job,
    create_restore_drill,
    run_backup_job,
    run_restore_drill,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.failover import (
    FailoverTransitionResult,
    evaluate_readiness,
    get_failover_status,
    issue_failover_token,
    promote_region,
    rollback_failover,
    set_write_freeze,
)
from nexusrag.services.entitlements import FEATURE_OPS_ADMIN, require_feature
from nexusrag.services.resilience import get_circuit_breaker_state
from nexusrag.services.telemetry import (
    availability,
    counters_snapshot,
    external_latency_by_integration,
    gauges_snapshot,
    p95_latency,
    request_latency_by_class,
    stream_duration_stats,
)


router = APIRouter(prefix="/ops", tags=["ops"], responses=DEFAULT_ERROR_RESPONSES)


class DRReadinessResponse(BaseModel):
    # Return DR readiness signals for operator dashboards.
    backup: dict[str, Any]
    restore_drill: dict[str, Any]
    integrity: dict[str, Any]
    status: str


class DRBackupJobResponse(BaseModel):
    # Describe a backup job for DR listings.
    id: int
    backup_type: str
    status: str
    manifest_uri: str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None


class DRBackupListResponse(BaseModel):
    # Wrap recent backup jobs for ops responses.
    items: list[DRBackupJobResponse]


class DRBackupTriggerResponse(BaseModel):
    # Report accepted backup triggers for async processing.
    job_id: int
    status: str


class DRRestoreDrillResponse(BaseModel):
    # Report restore drill execution status.
    drill_id: int
    status: str


class FailoverTokenRequest(BaseModel):
    # Require explicit purpose/reason for auditability.
    purpose: str
    reason: str | None = None


class FailoverTokenResponse(BaseModel):
    # Return token plaintext once; only hash is persisted.
    token_id: str
    token: str
    expires_at: datetime
    purpose: str


class FailoverPromoteRequest(BaseModel):
    # Gate promotion with a short-lived token and optional force override.
    target_region: str
    token: str
    reason: str | None = None
    force: bool = False


class FailoverRollbackRequest(BaseModel):
    # Gate rollback with a dedicated rollback token.
    token: str
    reason: str | None = None
    force: bool = False


class FailoverFreezeRequest(BaseModel):
    # Allow operators to toggle write freeze during incidents.
    freeze: bool
    reason: str | None = None


class FailoverStatusResponse(BaseModel):
    # Surface current failover state and region health to operators.
    active_primary_region: str
    epoch: int
    last_transition_at: str | None
    cooldown_until: str | None
    freeze_writes: bool
    local_region: dict[str, Any]
    regions: list[dict[str, Any]]


class FailoverReadinessResponse(BaseModel):
    # Report arbitration score and blockers to support safe promotion decisions.
    readiness_score: int
    recommendation: str
    blockers: list[str]
    replication_lag_seconds: int | None
    split_brain_risk: bool
    peer_signals: list[dict[str, Any]]


class FailoverActionResponse(BaseModel):
    # Return summarized transition results for promote/rollback APIs.
    event_id: int
    status: str
    from_region: str | None
    to_region: str | None
    epoch: int
    freeze_writes: bool
    blockers: list[str]


class AuthzPostureResponse(BaseModel):
    # Report ABAC/RLS guard posture for operational safety checks.
    tenant_predicate_required: bool
    enforcement_mode: str
    abac_enabled: bool
    default_deny: bool


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
    return success_response(request=request, data=payload)


@router.get(
    "/authz/posture",
    response_model=SuccessEnvelope[AuthzPostureResponse] | AuthzPostureResponse,
)
async def authz_posture(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> AuthzPostureResponse:
    # Surface ABAC guard posture for ops validation and rollout checks.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_OPS_ADMIN)
    settings = get_settings()
    payload = AuthzPostureResponse(
        tenant_predicate_required=settings.authz_require_tenant_predicate,
        enforcement_mode="guard",
        abac_enabled=settings.authz_abac_enabled,
        default_deny=settings.authz_default_deny,
    )
    return success_response(request=request, data=payload)


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
    return success_response(request=request, data=payload)


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
            "nexusrag_crypto_encrypt_ops_total": metrics_counters.get("crypto_encrypt_ops_total", 0),
            "nexusrag_crypto_decrypt_ops_total": metrics_counters.get("crypto_decrypt_ops_total", 0),
            "nexusrag_crypto_failures_total": metrics_counters.get("crypto_failures_total", 0),
            "nexusrag_key_rotation_jobs_total": metrics_counters.get("key_rotation_jobs_total", 0),
            "nexusrag_unencrypted_sensitive_items_total": metrics_counters.get(
                "unencrypted_sensitive_items_total", 0
            ),
            "nexusrag_failover_requests_total_completed": metrics_counters.get(
                "failover_requests_total.completed", 0
            ),
            "nexusrag_failover_requests_total_failed": metrics_counters.get(
                "failover_requests_total.failed", 0
            ),
            "nexusrag_failover_requests_total_rolled_back": metrics_counters.get(
                "failover_requests_total.rolled_back", 0
            ),
        }
    )
    payload["gauges"].update(
        {
            "nexusrag_write_frozen_state": gauges_snapshot().get("write_frozen_state", 0.0),
        }
    )
    # Include all telemetry gauges so region-specific failover gauges are visible.
    payload["telemetry_gauges"] = gauges_snapshot()
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
    return success_response(request=request, data=payload)


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
    return success_response(request=request, data=payload)


async def _run_backup_in_background(
    job_id: int,
    backup_type: str,
    principal: Principal,
    request_id: str | None,
) -> None:
    # Run backup jobs asynchronously to avoid blocking request threads.
    async with SessionLocal() as session:
        job = await session.get(BackupJob, job_id)
        if job is None:
            return
        await run_backup_job(
            session=session,
            job=job,
            backup_type=backup_type,
            output_dir=Path(get_settings().backup_local_dir),
            actor_type="api_key",
            tenant_id=principal.tenant_id,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            request_id=request_id,
        )


async def _run_restore_drill_in_background(
    manifest_uri: str,
    principal: Principal,
    request_id: str | None,
    drill_id: int,
) -> None:
    # Run restore drills asynchronously to keep ops endpoints responsive.
    async with SessionLocal() as session:
        await run_restore_drill(
            session=session,
            manifest_uri=manifest_uri,
            actor_type="api_key",
            tenant_id=principal.tenant_id,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            request_id=request_id,
            drill_id=drill_id,
        )


@router.get(
    "/dr/readiness",
    response_model=SuccessEnvelope[DRReadinessResponse] | DRReadinessResponse,
)
async def dr_readiness(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> DRReadinessResponse:
    # Summarize DR readiness for operators and alerts.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    settings = get_settings()
    status = "ready"

    last_success = (
        await db.execute(
            select(BackupJob)
            .where(
                BackupJob.status == "succeeded",
                BackupJob.tenant_scope == principal.tenant_id,
            )
            .order_by(BackupJob.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    last_drill = (
        await db.execute(
            select(RestoreDrill).order_by(RestoreDrill.completed_at.desc()).limit(1)
        )
    ).scalar_one_or_none()

    now = _utc_now()
    retention_days = settings.backup_retention_days
    last_success_at = last_success.completed_at if last_success else None
    last_drill_at = last_drill.completed_at if last_drill else None
    last_drill_result = last_drill.status if last_drill else "unknown"

    if not settings.backup_enabled:
        status = "not_ready"
    elif last_success_at is None:
        status = "not_ready"
    elif now - last_success_at > timedelta(days=retention_days):
        status = "at_risk"
    elif last_drill is None or last_drill.status != "passed":
        status = "at_risk"

    readiness = DRReadinessResponse(
        backup={
            "enabled": settings.backup_enabled,
            "last_success_at": last_success_at.isoformat() if last_success_at else None,
            "last_status": last_success.status if last_success else "unknown",
            "retention_days": retention_days,
        },
        restore_drill={
            "last_drill_at": last_drill_at.isoformat() if last_drill_at else None,
            "last_result": last_drill_result,
            "rto_seconds": last_drill.rto_seconds if last_drill else None,
            "rpo_seconds": int((now - last_success_at).total_seconds())
            if last_success_at
            else None,
        },
        integrity={
            "signature_required": settings.restore_require_signature,
            "last_manifest_verified_at": last_drill_at.isoformat() if last_drill_at else None,
        },
        status=status,
    )
    return success_response(request=request, data=readiness)


@router.get(
    "/dr/backups",
    response_model=SuccessEnvelope[DRBackupListResponse] | DRBackupListResponse,
)
async def dr_list_backups(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> DRBackupListResponse:
    # List recent backup jobs for ops visibility.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    result = await db.execute(
        select(BackupJob)
        .where(BackupJob.tenant_scope == principal.tenant_id)
        .order_by(BackupJob.started_at.desc())
        .limit(limit)
    )
    jobs = result.scalars().all()
    items = [
        DRBackupJobResponse(
            id=job.id,
            backup_type=job.backup_type,
            status=job.status,
            manifest_uri=job.manifest_uri,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_code=job.error_code,
            error_message=job.error_message,
        )
        for job in jobs
    ]
    return success_response(request=request, data=DRBackupListResponse(items=items))


@router.post(
    "/dr/backup",
    response_model=SuccessEnvelope[DRBackupTriggerResponse] | DRBackupTriggerResponse,
)
async def dr_trigger_backup(
    request: Request,
    backup_type: str = Query(default="all", pattern="^(full|schema|metadata|all)$"),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> DRBackupTriggerResponse:
    # Allow on-demand backups for DR readiness.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    settings = get_settings()
    if not settings.backup_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DR_NOT_READY",
                "message": "Backups are disabled",
            },
        )
    job = await create_backup_job(
        db,
        backup_type=backup_type,
        created_by_actor_id=principal.api_key_id,
        tenant_scope=principal.tenant_id,
        metadata={"source": "ops", "path": request.url.path},
    )
    request_ctx = get_request_context(request)
    asyncio.create_task(
        _run_backup_in_background(
            job.id,
            backup_type,
            principal,
            request_ctx["request_id"],
        )
    )
    return success_response(
        request=request,
        data=DRBackupTriggerResponse(job_id=job.id, status="accepted"),
    )


@router.post(
    "/dr/restore-drill",
    response_model=SuccessEnvelope[DRRestoreDrillResponse] | DRRestoreDrillResponse,
)
async def dr_restore_drill(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> DRRestoreDrillResponse:
    # Trigger a non-destructive restore drill from the latest backup.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    latest_backup = (
        await db.execute(
            select(BackupJob)
            .where(
                BackupJob.status == "succeeded",
                BackupJob.tenant_scope == principal.tenant_id,
            )
            .order_by(BackupJob.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_backup is None or not latest_backup.manifest_uri:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DR_NOT_READY",
                "message": "No successful backups available for restore drill",
            },
        )
    request_ctx = get_request_context(request)
    drill = await create_restore_drill(
        db,
        status="running",
        report_json=None,
        rto_seconds=None,
        verified_manifest_uri=latest_backup.manifest_uri,
    )
    asyncio.create_task(
        _run_restore_drill_in_background(
            latest_backup.manifest_uri,
            principal,
            request_ctx["request_id"],
            drill.id,
        )
    )
    return success_response(
        request=request,
        data=DRRestoreDrillResponse(drill_id=drill.id, status="accepted"),
    )


@router.get(
    "/failover/status",
    response_model=SuccessEnvelope[FailoverStatusResponse] | FailoverStatusResponse,
)
async def failover_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> FailoverStatusResponse:
    # Expose current failover/region state for operational decision making.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_OPS_ADMIN)
    payload = await get_failover_status(db)
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
        resource_id="failover.status",
        request_id=request_ctx["request_id"],
        metadata={"path": request.url.path},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=FailoverStatusResponse(**payload))


@router.get(
    "/failover/readiness",
    response_model=SuccessEnvelope[FailoverReadinessResponse] | FailoverReadinessResponse,
)
async def failover_readiness(
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> FailoverReadinessResponse:
    # Report readiness score/recommendation with explicit promotion blockers.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_OPS_ADMIN)
    readiness = await evaluate_readiness(db)
    request_ctx = get_request_context(request)
    if readiness.split_brain_risk:
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="failover.split_brain_detected",
            outcome="failure",
            resource_type="failover",
            resource_id="readiness",
            request_id=request_ctx["request_id"],
            metadata={"path": request.url.path, "blockers": readiness.blockers},
            error_code="SPLIT_BRAIN_RISK",
            commit=True,
            best_effort=True,
        )
    return success_response(
        request=request,
        data=FailoverReadinessResponse(
            readiness_score=readiness.readiness_score,
            recommendation=readiness.recommendation,
            blockers=readiness.blockers,
            replication_lag_seconds=readiness.replication_lag_seconds,
            split_brain_risk=readiness.split_brain_risk,
            peer_signals=readiness.peer_signals,
        ),
    )


@router.post(
    "/failover/request-token",
    response_model=SuccessEnvelope[FailoverTokenResponse] | FailoverTokenResponse,
)
async def failover_request_token(
    payload: FailoverTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> FailoverTokenResponse:
    # Require explicit one-time token issuance before promote/rollback operations.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_OPS_ADMIN)
    request_ctx = get_request_context(request)
    issued = await issue_failover_token(
        session=db,
        requested_by_actor_id=principal.api_key_id,
        purpose=payload.purpose,
        reason=payload.reason,
        tenant_id=principal.tenant_id,
        actor_role=principal.role,
        request_id=request_ctx["request_id"],
    )
    return success_response(
        request=request,
        data=FailoverTokenResponse(
            token_id=issued.token_id,
            token=issued.token,
            expires_at=issued.expires_at,
            purpose=payload.purpose,
        ),
    )


@router.post(
    "/failover/promote",
    response_model=SuccessEnvelope[FailoverActionResponse] | FailoverActionResponse,
)
async def failover_promote(
    payload: FailoverPromoteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> FailoverActionResponse:
    # Execute guarded failover promotion with token + readiness prechecks.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_OPS_ADMIN)
    request_ctx = get_request_context(request)
    result: FailoverTransitionResult = await promote_region(
        session=db,
        target_region=payload.target_region,
        plaintext_token=payload.token,
        reason=payload.reason,
        force=payload.force,
        requested_by_actor_id=principal.api_key_id,
        actor_role=principal.role,
        tenant_id=principal.tenant_id,
        request_id=request_ctx["request_id"],
    )
    return success_response(request=request, data=FailoverActionResponse(**result.__dict__))


@router.post(
    "/failover/rollback",
    response_model=SuccessEnvelope[FailoverActionResponse] | FailoverActionResponse,
)
async def failover_rollback(
    payload: FailoverRollbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> FailoverActionResponse:
    # Execute guarded rollback with dedicated rollback token semantics.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_OPS_ADMIN)
    request_ctx = get_request_context(request)
    result: FailoverTransitionResult = await rollback_failover(
        session=db,
        plaintext_token=payload.token,
        reason=payload.reason,
        requested_by_actor_id=principal.api_key_id,
        actor_role=principal.role,
        tenant_id=principal.tenant_id,
        request_id=request_ctx["request_id"],
    )
    return success_response(request=request, data=FailoverActionResponse(**result.__dict__))


@router.patch(
    "/failover/freeze-writes",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def failover_freeze_writes(
    payload: FailoverFreezeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("admin")),
) -> dict[str, Any]:
    # Allow operators to toggle write freeze without running a full promotion flow.
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_OPS_ADMIN)
    request_ctx = get_request_context(request)
    result = await set_write_freeze(
        session=db,
        freeze=payload.freeze,
        reason=payload.reason,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        tenant_id=principal.tenant_id,
        request_id=request_ctx["request_id"],
    )
    return success_response(request=request, data=result)
