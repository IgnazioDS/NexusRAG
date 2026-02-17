from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope
from nexusrag.core.config import get_settings
from nexusrag.domain.models import ChargebackReport, TenantBudget
from nexusrag.services.costs.aggregation import build_summary, breakdown_costs, current_year_month, month_bounds, timeseries
from nexusrag.services.entitlements import get_effective_entitlements


router = APIRouter(prefix="/self-serve/costs", tags=["self-serve"], responses=DEFAULT_ERROR_RESPONSES)


def _error_detail(code: str, message: str) -> dict[str, str]:
    # Standardize error payloads for self-serve cost endpoints.
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


class BudgetResponse(BaseModel):
    tenant_id: str
    monthly_budget_usd: float | None
    warn_ratio: float
    enforce_hard_cap: bool
    hard_cap_mode: str
    current_month_override_usd: float | None


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


def _budget_payload(tenant_id: str, budget: TenantBudget | None) -> BudgetResponse:
    # Normalize budget payloads for self-serve responses.
    settings = get_settings()
    if budget is None:
        return BudgetResponse(
            tenant_id=tenant_id,
            monthly_budget_usd=None,
            warn_ratio=settings.cost_default_warn_ratio,
            enforce_hard_cap=False,
            hard_cap_mode=settings.cost_default_hard_cap_mode,
            current_month_override_usd=None,
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
    )


def _chargeback_payload(row: ChargebackReport) -> ChargebackReportResponse:
    # Serialize chargeback reports for self-serve clients.
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
    # Return the current tenant budget configuration for self-serve admins.
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
    # Return spend summary for self-serve cost dashboards.
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
    # Return a time series of spend for self-serve dashboards.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.cost_visibility",
    )
    settings = get_settings()
    window = days or settings.cost_timeseries_default_days
    end = datetime.now(timezone.utc)
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
    # Return spend breakdown by dimension for self-serve admins.
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


@router.get(
    "/chargeback/latest",
    response_model=SuccessEnvelope[ChargebackReportResponse] | ChargebackReportResponse,
)
async def latest_chargeback(
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ChargebackReportResponse:
    # Return the most recent chargeback report for the tenant.
    await _require_cost_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key="feature.chargeback_reports",
    )
    result = await db.execute(
        select(ChargebackReport)
        .where(ChargebackReport.tenant_id == principal.tenant_id)
        .order_by(ChargebackReport.generated_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail=_error_detail("COST_CHARGEBACK_REPORT_NOT_FOUND", "No reports"))
    return _chargeback_payload(report)
