from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    ApiKey,
    AuditEvent,
    Document,
    Plan,
    PlanLimit,
    PlanUpgradeRequest,
    UsageCounter,
    User,
)
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.auth.api_keys import generate_api_key, normalize_role
from nexusrag.services.billing_webhook import send_billing_webhook_event
from nexusrag.services.entitlements import (
    DEFAULT_PLAN_ID,
    FEATURE_BILLING_WEBHOOK_TEST,
    FEATURE_KEYS,
    FeatureEntitlement,
    get_active_plan_assignment,
    get_effective_entitlements,
    require_feature,
)
from nexusrag.services.self_serve import enforce_key_limit
from nexusrag.services.usage_dashboard import aggregate_request_counts, build_timeseries_points


router = APIRouter(prefix="/self-serve", tags=["self-serve"])


class ApiKeyCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    role: Literal["reader", "editor", "admin"]


class ApiKeyResponse(BaseModel):
    key_id: str
    key_prefix: str
    name: str | None
    role: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None
    is_active: bool


class ApiKeyCreateResponse(ApiKeyResponse):
    api_key: str


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyResponse]


class UsageSummaryResponse(BaseModel):
    window_days: int
    requests: dict[str, Any]
    quota: dict[str, Any]
    rate_limit_hits: dict[str, Any]
    ingestion: dict[str, Any]


class UsageTimeseriesResponse(BaseModel):
    metric: str
    granularity: str
    points: list[dict[str, Any]]


class PlanResponse(BaseModel):
    tenant_id: str
    plan_id: str
    plan_name: str | None
    entitlements: list[dict[str, Any]]
    quota: dict[str, Any]


class PlanUpgradeRequestPayload(BaseModel):
    target_plan: Literal["pro", "enterprise"]
    reason: str | None = Field(default=None, max_length=1024)


class PlanUpgradeResponse(BaseModel):
    request_id: int
    status: str


class BillingWebhookTestResponse(BaseModel):
    sent: bool
    status_code: int | None
    delivery_id: str
    message: str


def _utc_now() -> datetime:
    # Use UTC to keep self-serve reporting aligned with quota periods.
    return datetime.now(timezone.utc)


def _quota_snapshot(limit: int | None, used: int) -> dict[str, Any]:
    # Render quota snapshots with remaining counts while preserving unlimited semantics.
    remaining = None if limit is None else max(limit - used, 0)
    return {"limit": limit, "used": used, "remaining": remaining}


async def _get_quota_state(db: AsyncSession, tenant_id: str) -> dict[str, Any]:
    # Load current quota usage and plan settings without mutating counters.
    now = _utc_now()
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    result = await db.execute(select(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
    plan_limit = result.scalar_one_or_none()

    soft_cap_ratio = plan_limit.soft_cap_ratio if plan_limit else 0.8
    hard_cap_mode = "enforce" if (plan_limit.hard_cap_enabled if plan_limit else True) else "observe"

    result = await db.execute(
        select(UsageCounter).where(
            UsageCounter.tenant_id == tenant_id,
            UsageCounter.period_type == "day",
            UsageCounter.period_start == day_start,
        )
    )
    day_counter = result.scalar_one_or_none()
    day_used = int(day_counter.requests_count) if day_counter else 0

    result = await db.execute(
        select(UsageCounter).where(
            UsageCounter.tenant_id == tenant_id,
            UsageCounter.period_type == "month",
            UsageCounter.period_start == month_start,
        )
    )
    month_counter = result.scalar_one_or_none()
    month_used = int(month_counter.requests_count) if month_counter else 0

    day_limit = plan_limit.daily_requests_limit if plan_limit else None
    month_limit = plan_limit.monthly_requests_limit if plan_limit else None

    day_snapshot = _quota_snapshot(day_limit, day_used)
    month_snapshot = _quota_snapshot(month_limit, month_used)

    soft_cap_reached = False
    if day_limit:
        soft_cap_reached = soft_cap_reached or day_used >= day_limit * soft_cap_ratio
    if month_limit:
        soft_cap_reached = soft_cap_reached or month_used >= month_limit * soft_cap_ratio

    return {
        "day": day_snapshot,
        "month": month_snapshot,
        "soft_cap_reached": soft_cap_reached,
        "hard_cap_mode": hard_cap_mode,
    }


async def _audit(
    *,
    db: AsyncSession,
    principal: Principal,
    request: Request,
    event_type: str,
    outcome: str,
    metadata: dict[str, Any] | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    error_code: str | None = None,
) -> None:
    # Centralize self-serve audit logging with consistent request context.
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type=event_type,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata=metadata or {},
        error_code=error_code,
        commit=True,
        best_effort=True,
    )


@router.post("/api-keys")
async def create_api_key(
    request: Request,
    payload: ApiKeyCreateRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    # Allow tenant admins to create API keys for their tenant.
    settings = get_settings()
    max_active = settings.self_serve_max_active_keys
    try:
        active_count = await db.scalar(
            select(func.count(ApiKey.id))
            .select_from(ApiKey)
            .join(User, ApiKey.user_id == User.id)
            .where(
                ApiKey.tenant_id == principal.tenant_id,
                ApiKey.revoked_at.is_(None),
                User.is_active.is_(True),
            )
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while counting API keys") from exc

    try:
        enforce_key_limit(active_count, max_active)
    except HTTPException as exc:
        await _audit(
            db=db,
            principal=principal,
            request=request,
            event_type="selfserve.api_key.created",
            outcome="failure",
            metadata={"reason": "limit_reached", "max_active": max_active},
            error_code="KEY_LIMIT_REACHED",
        )
        raise exc

    try:
        role = normalize_role(payload.role)
        user_id = uuid4().hex
        key_id, raw_key, key_prefix, key_hash = generate_api_key()
        user = User(
            id=user_id,
            tenant_id=principal.tenant_id,
            email=None,
            role=role,
            is_active=True,
        )
        api_key = ApiKey(
            id=key_id,
            user_id=user_id,
            tenant_id=principal.tenant_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            name=payload.name,
        )
        db.add(user)
        await db.flush()
        db.add(api_key)
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while creating API key") from exc

    await _audit(
        db=db,
        principal=principal,
        request=request,
        event_type="selfserve.api_key.created",
        outcome="success",
        resource_type="api_key",
        resource_id=api_key.id,
        metadata={"key_id": api_key.id, "name": api_key.name, "role": role},
    )

    created_at = api_key.created_at.isoformat()
    return ApiKeyCreateResponse(
        key_id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        role=role,
        created_at=created_at,
        last_used_at=None,
        revoked_at=None,
        is_active=True,
        api_key=raw_key,
    )


@router.get("/api-keys")
async def list_api_keys(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyListResponse:
    # List API key metadata without exposing secrets.
    try:
        result = await db.execute(
            select(ApiKey, User)
            .join(User, ApiKey.user_id == User.id)
            .where(ApiKey.tenant_id == principal.tenant_id)
            .order_by(ApiKey.created_at.desc())
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while listing API keys") from exc

    items: list[ApiKeyResponse] = []
    for api_key, user in result.all():
        is_active = bool(user.is_active) and api_key.revoked_at is None
        items.append(
            ApiKeyResponse(
                key_id=api_key.id,
                key_prefix=api_key.key_prefix,
                name=api_key.name,
                role=user.role,
                created_at=api_key.created_at.isoformat(),
                last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
                revoked_at=api_key.revoked_at.isoformat() if api_key.revoked_at else None,
                is_active=is_active,
            )
        )

    await _audit(
        db=db,
        principal=principal,
        request=request,
        event_type="selfserve.api_key.listed",
        outcome="success",
        metadata={"count": len(items)},
    )

    return ApiKeyListResponse(items=items)


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyResponse:
    # Allow tenant admins to revoke API keys idempotently.
    try:
        result = await db.execute(
            select(ApiKey, User)
            .join(User, ApiKey.user_id == User.id)
            .where(ApiKey.id == key_id, ApiKey.tenant_id == principal.tenant_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="API key not found")
        api_key, user = row
        if api_key.revoked_at is None:
            api_key.revoked_at = _utc_now()
            await db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while revoking API key") from exc

    await _audit(
        db=db,
        principal=principal,
        request=request,
        event_type="selfserve.api_key.revoked",
        outcome="success",
        resource_type="api_key",
        resource_id=api_key.id,
        metadata={"key_id": api_key.id},
    )

    is_active = bool(user.is_active) and api_key.revoked_at is None
    return ApiKeyResponse(
        key_id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        role=user.role,
        created_at=api_key.created_at.isoformat(),
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        revoked_at=api_key.revoked_at.isoformat() if api_key.revoked_at else None,
        is_active=is_active,
    )


@router.get("/usage/summary")
async def usage_summary(
    request: Request,
    window_days: int = Query(default=30, ge=1, le=90),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> UsageSummaryResponse:
    # Provide a tenant usage summary for the requested window.
    window_start = _utc_now() - timedelta(days=window_days)
    try:
        result = await db.execute(
            select(AuditEvent.metadata_json)
            .where(
                AuditEvent.tenant_id == principal.tenant_id,
                AuditEvent.event_type == "auth.access.success",
                AuditEvent.occurred_at >= window_start,
            )
            .order_by(AuditEvent.occurred_at.desc())
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while aggregating usage") from exc

    metadata_rows = [row[0] for row in result.all()]
    counts = aggregate_request_counts(metadata_rows)

    try:
        rate_limit_row = await db.execute(
            select(func.count(AuditEvent.id), func.max(AuditEvent.occurred_at)).where(
                AuditEvent.tenant_id == principal.tenant_id,
                AuditEvent.event_type == "security.rate_limited",
                AuditEvent.occurred_at >= window_start,
            )
        )
        rate_limit_count, rate_limit_last = rate_limit_row.one()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching rate limit hits") from exc

    try:
        status_rows = await db.execute(
            select(Document.status, func.count(Document.id))
            .where(Document.tenant_id == principal.tenant_id)
            .group_by(Document.status)
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while aggregating ingestion") from exc

    ingestion_counts = {"queued": 0, "processing": 0, "succeeded": 0, "failed": 0}
    for status, count in status_rows.all():
        if status in ingestion_counts:
            ingestion_counts[status] = int(count or 0)

    quota_state = await _get_quota_state(db, principal.tenant_id)

    await _audit(
        db=db,
        principal=principal,
        request=request,
        event_type="selfserve.usage.viewed",
        outcome="success",
        metadata={"window_days": window_days},
    )

    return UsageSummaryResponse(
        window_days=window_days,
        requests={
            "total": counts.total,
            "by_route_class": counts.by_route_class,
        },
        quota=quota_state,
        rate_limit_hits={
            "count": int(rate_limit_count or 0),
            "last_at": rate_limit_last.isoformat() if rate_limit_last else None,
        },
        ingestion=ingestion_counts,
    )


@router.get("/usage/timeseries")
async def usage_timeseries(
    request: Request,
    metric: str = Query(default="requests", pattern="^requests$"),
    granularity: str = Query(default="day", pattern="^day$"),
    days: int = Query(default=30, ge=1, le=90),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> UsageTimeseriesResponse:
    # Return tenant usage series for charting.
    window_start = _utc_now() - timedelta(days=days)
    try:
        rows = await db.execute(
            select(func.date_trunc("day", AuditEvent.occurred_at), func.count(AuditEvent.id))
            .where(
                AuditEvent.tenant_id == principal.tenant_id,
                AuditEvent.event_type == "auth.access.success",
                AuditEvent.occurred_at >= window_start,
            )
            .group_by(func.date_trunc("day", AuditEvent.occurred_at))
            .order_by(func.date_trunc("day", AuditEvent.occurred_at))
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while building usage series") from exc

    counts_by_date: dict[date, int] = {}
    for bucket, count in rows.all():
        counts_by_date[bucket.date()] = int(count or 0)

    start_date = (window_start.date())
    points = build_timeseries_points(start_date=start_date, days=days, counts_by_date=counts_by_date)

    await _audit(
        db=db,
        principal=principal,
        request=request,
        event_type="selfserve.usage.viewed",
        outcome="success",
        metadata={"metric": metric, "granularity": granularity, "days": days},
    )

    return UsageTimeseriesResponse(metric=metric, granularity=granularity, points=points)


@router.get("/plan")
async def get_self_serve_plan(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PlanResponse:
    # Provide the current plan, entitlements, and quota limits to tenant admins.
    assignment = await get_active_plan_assignment(db, principal.tenant_id)
    plan_id = assignment.plan_id if assignment else DEFAULT_PLAN_ID
    try:
        plan_row = await db.execute(select(Plan).where(Plan.id == plan_id))
        plan = plan_row.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching plan") from exc

    entitlements = await get_effective_entitlements(db, principal.tenant_id)
    features = [
        {
            "feature_key": feature_key,
            "enabled": entitlements.get(feature_key, FeatureEntitlement(False, None)).enabled,
            "config_json": entitlements.get(feature_key, FeatureEntitlement(False, None)).config,
        }
        for feature_key in sorted(FEATURE_KEYS)
    ]
    quota_state = await _get_quota_state(db, principal.tenant_id)

    await _audit(
        db=db,
        principal=principal,
        request=request,
        event_type="selfserve.plan.viewed",
        outcome="success",
        metadata={"plan_id": plan_id},
    )

    return PlanResponse(
        tenant_id=principal.tenant_id,
        plan_id=plan_id,
        plan_name=plan.name if plan else None,
        entitlements=features,
        quota=quota_state,
    )


@router.post("/plan/upgrade-request", status_code=202)
async def upgrade_plan_request(
    request: Request,
    payload: PlanUpgradeRequestPayload,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PlanUpgradeResponse:
    # Record a tenant plan upgrade request for review workflows.
    assignment = await get_active_plan_assignment(db, principal.tenant_id)
    current_plan_id = assignment.plan_id if assignment else DEFAULT_PLAN_ID
    try:
        plan_row = await db.execute(select(Plan).where(Plan.id == payload.target_plan))
        target_plan = plan_row.scalar_one_or_none()
        if target_plan is None or not target_plan.is_active:
            raise HTTPException(status_code=404, detail="Target plan not found")
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while validating target plan") from exc

    try:
        upgrade_request = PlanUpgradeRequest(
            tenant_id=principal.tenant_id,
            current_plan_id=current_plan_id,
            target_plan_id=payload.target_plan,
            reason=payload.reason,
            status="pending",
            requested_by_actor_id=principal.api_key_id,
        )
        db.add(upgrade_request)
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while creating upgrade request") from exc

    await _audit(
        db=db,
        principal=principal,
        request=request,
        event_type="plan.upgrade_requested",
        outcome="success",
        resource_type="plan",
        resource_id=str(upgrade_request.id),
        metadata={
            "current_plan": current_plan_id,
            "target_plan": payload.target_plan,
            "reason": payload.reason,
        },
    )

    webhook_payload = {
        "event_type": "billing.upgrade_requested",
        "tenant_id": principal.tenant_id,
        "current_plan": current_plan_id,
        "target_plan": payload.target_plan,
        "reason": payload.reason,
        "request_id": upgrade_request.id,
        "timestamp": _utc_now().isoformat(),
    }
    await send_billing_webhook_event(event_type="billing.upgrade_requested", payload=webhook_payload)

    return PlanUpgradeResponse(request_id=upgrade_request.id, status=upgrade_request.status)


@router.post("/billing/webhook-test")
async def billing_webhook_test(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> BillingWebhookTestResponse:
    # Send a signed webhook test payload when entitlements and config allow.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_BILLING_WEBHOOK_TEST,
    )

    delivery_id = str(uuid4())
    payload = {
        "event_type": "billing.webhook.test",
        "tenant_id": principal.tenant_id,
        "delivery_id": delivery_id,
        "timestamp": _utc_now().isoformat(),
    }
    result = await send_billing_webhook_event(
        event_type="billing.webhook.test",
        payload=payload,
        require_enabled=True,
    )

    if result.message == "Billing webhook is disabled" or result.message == "Billing webhook is not configured":
        await _audit(
            db=db,
            principal=principal,
            request=request,
            event_type="selfserve.billing_webhook_tested",
            outcome="failure",
            metadata={"delivery_id": delivery_id, "reason": result.message},
            error_code="BILLING_WEBHOOK_NOT_CONFIGURED",
        )
        raise HTTPException(
            status_code=400,
            detail={"code": "BILLING_WEBHOOK_NOT_CONFIGURED", "message": result.message},
        )

    await _audit(
        db=db,
        principal=principal,
        request=request,
        event_type="selfserve.billing_webhook_tested",
        outcome="success" if result.sent else "failure",
        metadata={
            "delivery_id": delivery_id,
            "status_code": result.status_code,
            "sent": result.sent,
        },
    )

    return BillingWebhookTestResponse(
        sent=result.sent,
        status_code=result.status_code,
        delivery_id=delivery_id,
        message=result.message,
    )
