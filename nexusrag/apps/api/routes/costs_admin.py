from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, idempotency_key_header, reject_tenant_id_in_body, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import ChargebackReport, PricingCatalog, TenantBudget
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.costs.aggregation import build_summary, breakdown_costs, current_year_month, month_bounds, timeseries
from nexusrag.services.entitlements import get_effective_entitlements
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)


router = APIRouter(prefix="/admin/costs", tags=["costs"], responses=DEFAULT_ERROR_RESPONSES)


def _error_detail(code: str, message: str) -> dict[str, str]:
    # Standardize error payloads for cost governance endpoints.
    return {"code": code, "message": message}


async def _require_cost_feature(
    *,
    session: AsyncSession,
    tenant_id: str,
    feature_key: str,
) -> None:
    # Enforce cost entitlements with a stable cost-specific error code.
    entitlements = await get_effective_entitlements(session, tenant_id)
    entitlement = entitlements.get(feature_key)
    if not entitlement or not entitlement.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "COST_FEATURE_NOT_ENABLED",
                "message": "Cost feature not enabled for tenant plan",
                "feature_key": feature_key,
            },
        )


def _utc_now() -> datetime:
    # Use UTC to keep period calculations deterministic across regions.
    return datetime.now(timezone.utc)


class BudgetResponse(BaseModel):
    tenant_id: str
    monthly_budget_usd: float | None
    warn_ratio: float
    enforce_hard_cap: bool
    hard_cap_mode: str
    current_month_override_usd: float | None
    created_at: str | None
    updated_at: str | None


class BudgetPatchRequest(BaseModel):
    monthly_budget_usd: float | None = Field(default=None, ge=0)
    warn_ratio: float | None = Field(default=None, gt=0, lt=1)
    enforce_hard_cap: bool | None = None
    hard_cap_mode: Literal["block", "degrade"] | None = None
    current_month_override_usd: float | None = Field(default=None, ge=0)

    # Reject unknown fields to avoid silent config drift.
    model_config = {"extra": "forbid"}


class SpendSummaryResponse(BaseModel):
    period: str
    year_month: str
    total_usd: float
    by_component: dict[str, float]
    by_provider: dict[str, float]
    by_route_class: dict[str, float]


class SpendTimeseriesResponse(BaseModel):
    window_days: int
    granularity: str
    points: list[dict[str, Any]]


class SpendBreakdownResponse(BaseModel):
    period: str
    year_month: str
    by: str
    breakdown: dict[str, float]


class PricingCreateRequest(BaseModel):
    version: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=64)
    component: str = Field(min_length=1, max_length=64)
    rate_type: Literal["per_1k_tokens", "per_char", "per_mb", "per_request", "per_second"]
    rate_value_usd: float = Field(gt=0)
    effective_from: datetime
    effective_to: datetime | None = None
    active: bool = True
    metadata_json: dict[str, Any] | None = None

    # Reject unknown fields to keep pricing updates explicit.
    model_config = {"extra": "forbid"}


class PricingResponse(BaseModel):
    id: str
    version: str
    provider: str
    component: str
    rate_type: str
    rate_value_usd: float
    effective_from: str
    effective_to: str | None
    active: bool
    metadata_json: dict[str, Any] | None


class PricingListResponse(BaseModel):
    items: list[PricingResponse]


class ChargebackReportResponse(BaseModel):
    id: str
    tenant_id: str
    period_start: str
    period_end: str
    currency: str
    total_usd: float
    breakdown_json: dict[str, Any] | None
    generated_at: str
    generated_by: str | None


class ChargebackListResponse(BaseModel):
    items: list[ChargebackReportResponse]


def _budget_payload(tenant_id: str, budget: TenantBudget | None) -> BudgetResponse:
    # Normalize budget payloads for API responses.
    settings = get_settings()
    if budget is None:
        return BudgetResponse(
            tenant_id=tenant_id,
            monthly_budget_usd=None,
            warn_ratio=settings.cost_default_warn_ratio,
            enforce_hard_cap=False,
            hard_cap_mode=settings.cost_default_hard_cap_mode,
            current_month_override_usd=None,
            created_at=None,
            updated_at=None,
        )
    return BudgetResponse(
        tenant_id=tenant_id,
        monthly_budget_usd=float(budget.monthly_budget_usd),
        warn_ratio=float(budget.warn_ratio),
        enforce_hard_cap=bool(budget.enforce_hard_cap),
        hard_cap_mode=budget.hard_cap_mode,
        current_month_override_usd=float(budget.current_month_override_usd)
        if budget.current_month_override_usd is not None
        else None,
        created_at=budget.created_at.isoformat() if budget.created_at else None,
        updated_at=budget.updated_at.isoformat() if budget.updated_at else None,
    )


def _pricing_payload(row: PricingCatalog) -> PricingResponse:
    # Serialize pricing rows for client consumption.
    return PricingResponse(
        id=row.id,
        version=row.version,
        provider=row.provider,
        component=row.component,
        rate_type=row.rate_type,
        rate_value_usd=float(row.rate_value_usd),
        effective_from=row.effective_from.isoformat(),
        effective_to=row.effective_to.isoformat() if row.effective_to else None,
        active=bool(row.active),
        metadata_json=row.metadata_json,
    )


def _chargeback_payload(row: ChargebackReport) -> ChargebackReportResponse:
    # Normalize chargeback reports for API responses.
    return ChargebackReportResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        period_start=row.period_start.isoformat(),
        period_end=row.period_end.isoformat(),
        currency=row.currency,
        total_usd=float(row.total_usd),
        breakdown_json=row.breakdown_json,
        generated_at=row.generated_at.isoformat(),
        generated_by=row.generated_by,
    )


@router.get(
    "/budget",
    response_model=SuccessEnvelope[BudgetResponse] | BudgetResponse,
)
async def get_budget(
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> BudgetResponse:
    # Return the current tenant budget configuration.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.cost_controls",
    )
    result = await db.execute(
        select(TenantBudget).where(TenantBudget.tenant_id == principal.tenant_id)
    )
    budget = result.scalar_one_or_none()
    return _budget_payload(principal.tenant_id, budget)


@router.patch(
    "/budget",
    response_model=SuccessEnvelope[BudgetResponse] | BudgetResponse,
)
async def patch_budget(
    request: Request,
    payload: BudgetPatchRequest,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> BudgetResponse:
    # Update tenant budget settings with validation and audit logging.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.cost_controls",
    )
    if payload.warn_ratio is not None and not (0 < payload.warn_ratio < 1):
        raise HTTPException(
            status_code=422,
            detail=_error_detail("COST_INVALID_BUDGET_CONFIG", "warn_ratio must be between 0 and 1"),
        )
    if payload.hard_cap_mode is not None and payload.hard_cap_mode not in {"block", "degrade"}:
        raise HTTPException(
            status_code=422,
            detail=_error_detail("COST_INVALID_BUDGET_CONFIG", "hard_cap_mode must be block or degrade"),
        )

    request_hash = compute_request_hash({"payload": payload.model_dump()})
    idem_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    result = await db.execute(
        select(TenantBudget).where(TenantBudget.tenant_id == principal.tenant_id)
    )
    budget = result.scalar_one_or_none()
    if budget is None:
        budget = TenantBudget(
            id=uuid4().hex,
            tenant_id=principal.tenant_id,
            monthly_budget_usd=payload.monthly_budget_usd or 0,
            warn_ratio=payload.warn_ratio or get_settings().cost_default_warn_ratio,
            enforce_hard_cap=bool(payload.enforce_hard_cap) if payload.enforce_hard_cap is not None else False,
            hard_cap_mode=payload.hard_cap_mode or get_settings().cost_default_hard_cap_mode,
            current_month_override_usd=payload.current_month_override_usd,
        )
        db.add(budget)
    else:
        if payload.monthly_budget_usd is not None:
            budget.monthly_budget_usd = payload.monthly_budget_usd
        if payload.warn_ratio is not None:
            budget.warn_ratio = payload.warn_ratio
        if payload.enforce_hard_cap is not None:
            budget.enforce_hard_cap = payload.enforce_hard_cap
        if payload.hard_cap_mode is not None:
            budget.hard_cap_mode = payload.hard_cap_mode
        if payload.current_month_override_usd is not None:
            budget.current_month_override_usd = payload.current_month_override_usd

    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=_error_detail("DB_ERROR", "Database error while updating budget")) from exc

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="cost.budget.updated",
        outcome="success",
        resource_type="tenant_budget",
        resource_id=budget.id,
        request_id=request_ctx.get("request_id"),
        ip_address=request_ctx.get("ip_address"),
        user_agent=request_ctx.get("user_agent"),
        metadata={"monthly_budget_usd": float(budget.monthly_budget_usd), "warn_ratio": float(budget.warn_ratio)},
        commit=True,
        best_effort=True,
    )

    response = _budget_payload(principal.tenant_id, budget)
    payload_body = success_response(request=request, data=response)
    await store_idempotency_response(
        db=db,
        context=idem_ctx,
        response_status=200,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.get(
    "/spend/summary",
    response_model=SuccessEnvelope[SpendSummaryResponse] | SpendSummaryResponse,
)
async def spend_summary(
    period: Literal["month"] = Query(default="month"),
    year_month: str | None = Query(default=None),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> SpendSummaryResponse:
    # Return cost summary totals for the requested period.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.cost_visibility",
    )
    ym = year_month or current_year_month()
    start, end = month_bounds(ym)
    summary = await build_summary(session=db, tenant_id=principal.tenant_id, start=start, end=end)
    return SpendSummaryResponse(
        period=period,
        year_month=ym,
        total_usd=float(summary.total_usd),
        by_component={k: float(v) for k, v in summary.by_component.items()},
        by_provider={k: float(v) for k, v in summary.by_provider.items()},
        by_route_class={k: float(v) for k, v in summary.by_route_class.items()},
    )


@router.get(
    "/spend/timeseries",
    response_model=SuccessEnvelope[SpendTimeseriesResponse] | SpendTimeseriesResponse,
)
async def spend_timeseries(
    days: int | None = Query(default=None, ge=1, le=365),
    granularity: Literal["day", "hour"] = Query(default="day"),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> SpendTimeseriesResponse:
    # Return a time-bucketed cost series for dashboards.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.cost_visibility",
    )
    settings = get_settings()
    window = days or settings.cost_timeseries_default_days
    end = _utc_now()
    start = end - timedelta(days=window)
    points = await timeseries(
        session=db,
        tenant_id=principal.tenant_id,
        start=start,
        end=end,
        granularity=granularity,
    )
    return SpendTimeseriesResponse(window_days=window, granularity=granularity, points=points)


@router.get(
    "/spend/breakdown",
    response_model=SuccessEnvelope[SpendBreakdownResponse] | SpendBreakdownResponse,
)
async def spend_breakdown(
    period: Literal["month"] = Query(default="month"),
    year_month: str | None = Query(default=None),
    by: Literal["component", "provider", "route_class"] = Query(default="component"),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> SpendBreakdownResponse:
    # Return spend grouped by the requested dimension.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.cost_visibility",
    )
    ym = year_month or current_year_month()
    start, end = month_bounds(ym)
    breakdown = await breakdown_costs(session=db, tenant_id=principal.tenant_id, start=start, end=end, by=by)
    return SpendBreakdownResponse(
        period=period,
        year_month=ym,
        by=by,
        breakdown={key: float(value) for key, value in breakdown.items()},
    )


@router.post(
    "/pricing/catalog",
    status_code=201,
    response_model=SuccessEnvelope[PricingResponse] | PricingResponse,
)
async def create_pricing(
    request: Request,
    payload: PricingCreateRequest,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PricingResponse:
    # Create pricing catalog entries for deterministic cost calculation.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.cost_controls",
    )
    request_hash = compute_request_hash({"payload": payload.model_dump()})
    idem_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    if payload.effective_to and payload.effective_to <= payload.effective_from:
        raise HTTPException(
            status_code=422,
            detail=_error_detail("COST_PRICING_INVALID", "effective_to must be after effective_from"),
        )

    overlap_query = (
        select(PricingCatalog)
        .where(
            PricingCatalog.provider == payload.provider,
            PricingCatalog.component == payload.component,
            PricingCatalog.rate_type == payload.rate_type,
            PricingCatalog.active.is_(True),
            PricingCatalog.effective_from <= (payload.effective_to or payload.effective_from),
            or_(
                PricingCatalog.effective_to.is_(None),
                PricingCatalog.effective_to >= payload.effective_from,
            ),
        )
        .limit(1)
    )
    overlap = (await db.execute(overlap_query)).scalar_one_or_none()
    if overlap is not None:
        raise HTTPException(
            status_code=422,
            detail=_error_detail("COST_PRICING_INVALID", "Active pricing overlap detected"),
        )

    row = PricingCatalog(
        id=uuid4().hex,
        version=payload.version,
        provider=payload.provider,
        component=payload.component,
        rate_type=payload.rate_type,
        rate_value_usd=payload.rate_value_usd,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        active=payload.active,
        metadata_json=payload.metadata_json,
    )
    db.add(row)
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=_error_detail("DB_ERROR", "Database error while creating pricing")) from exc

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="cost.pricing.updated",
        outcome="success",
        resource_type="pricing_catalog",
        resource_id=row.id,
        request_id=request_ctx.get("request_id"),
        ip_address=request_ctx.get("ip_address"),
        user_agent=request_ctx.get("user_agent"),
        metadata={"provider": row.provider, "component": row.component, "rate_type": row.rate_type},
        commit=True,
        best_effort=True,
    )

    response = _pricing_payload(row)
    payload_body = success_response(request=request, data=response)
    await store_idempotency_response(
        db=db,
        context=idem_ctx,
        response_status=201,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.get(
    "/pricing/catalog",
    response_model=SuccessEnvelope[PricingListResponse] | PricingListResponse,
)
async def list_pricing(
    active: bool | None = Query(default=None),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PricingListResponse:
    # List pricing catalog entries for inspection.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.cost_controls",
    )
    query = select(PricingCatalog)
    if active is not None:
        query = query.where(PricingCatalog.active.is_(bool(active)))
    result = await db.execute(query.order_by(PricingCatalog.effective_from.desc()))
    items = [_pricing_payload(row) for row in result.scalars().all()]
    if active is True and not items:
        # Surface missing active pricing as an actionable configuration error.
        raise HTTPException(
            status_code=422,
            detail=_error_detail("COST_PRICING_NOT_FOUND", "No active pricing rates configured"),
        )
    return PricingListResponse(items=items)


@router.post(
    "/chargeback/generate",
    response_model=SuccessEnvelope[ChargebackReportResponse] | ChargebackReportResponse,
)
async def generate_chargeback(
    request: Request,
    period_start: str = Query(...),
    period_end: str = Query(...),
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ChargebackReportResponse:
    # Generate a chargeback report for the requested period.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.chargeback_reports",
    )
    try:
        start = datetime.fromisoformat(period_start)
        end = datetime.fromisoformat(period_end)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=_error_detail("COST_CHARGEBACK_RANGE_INVALID", "Invalid period range"),
        ) from exc
    if end <= start:
        raise HTTPException(
            status_code=400,
            detail=_error_detail("COST_CHARGEBACK_RANGE_INVALID", "period_end must be after period_start"),
        )

    request_hash = compute_request_hash({"period_start": period_start, "period_end": period_end})
    idem_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    summary = await build_summary(session=db, tenant_id=principal.tenant_id, start=start, end=end)
    breakdown = {
        "component": {k: float(v) for k, v in summary.by_component.items()},
        "provider": {k: float(v) for k, v in summary.by_provider.items()},
        "route_class": {k: float(v) for k, v in summary.by_route_class.items()},
    }

    report = ChargebackReport(
        id=uuid4().hex,
        tenant_id=principal.tenant_id,
        period_start=start,
        period_end=end,
        currency="USD",
        total_usd=float(summary.total_usd),
        breakdown_json=breakdown,
        generated_at=_utc_now(),
        generated_by=principal.api_key_id,
    )
    db.add(report)
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while generating chargeback report"),
        ) from exc

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="cost.chargeback.generated",
        outcome="success",
        resource_type="chargeback_report",
        resource_id=report.id,
        request_id=request_ctx.get("request_id"),
        ip_address=request_ctx.get("ip_address"),
        user_agent=request_ctx.get("user_agent"),
        metadata={"period_start": period_start, "period_end": period_end},
        commit=True,
        best_effort=True,
    )

    response = _chargeback_payload(report)
    payload_body = success_response(request=request, data=response)
    await store_idempotency_response(
        db=db,
        context=idem_ctx,
        response_status=200,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.get(
    "/chargeback/reports",
    response_model=SuccessEnvelope[ChargebackListResponse] | ChargebackListResponse,
)
async def list_chargeback_reports(
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ChargebackListResponse:
    # List chargeback reports for tenant review.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.chargeback_reports",
    )
    result = await db.execute(
        select(ChargebackReport)
        .where(ChargebackReport.tenant_id == principal.tenant_id)
        .order_by(ChargebackReport.generated_at.desc())
    )
    reports = [_chargeback_payload(row) for row in result.scalars().all()]
    return ChargebackListResponse(items=reports)


@router.get(
    "/chargeback/reports/{report_id}",
    response_model=SuccessEnvelope[ChargebackReportResponse] | ChargebackReportResponse,
)
async def get_chargeback_report(
    report_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ChargebackReportResponse:
    # Fetch a single chargeback report by id.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.chargeback_reports",
    )
    result = await db.execute(
        select(ChargebackReport).where(
            ChargebackReport.id == report_id,
            ChargebackReport.tenant_id == principal.tenant_id,
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=_error_detail("COST_CHARGEBACK_REPORT_NOT_FOUND", "Report not found"),
        )
    return _chargeback_payload(report)
