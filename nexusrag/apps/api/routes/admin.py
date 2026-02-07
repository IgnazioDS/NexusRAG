from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.domain.models import PlanLimit, UsageCounter
from nexusrag.services.quota import parse_period_start


router = APIRouter(prefix="/admin", tags=["admin"])


class PlanLimitResponse(BaseModel):
    tenant_id: str
    daily_requests_limit: int | None
    monthly_requests_limit: int | None
    daily_tokens_limit: int | None
    monthly_tokens_limit: int | None
    soft_cap_ratio: float
    hard_cap_enabled: bool


class PlanLimitPatchRequest(BaseModel):
    daily_requests_limit: int | None = Field(default=None, ge=0)
    monthly_requests_limit: int | None = Field(default=None, ge=0)
    daily_tokens_limit: int | None = Field(default=None, ge=0)
    monthly_tokens_limit: int | None = Field(default=None, ge=0)
    soft_cap_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    hard_cap_enabled: bool | None = Field(default=None)


class UsageSummaryResponse(BaseModel):
    tenant_id: str
    period_type: str
    period_start: str
    requests_count: int
    estimated_tokens_count: int | None


def _ensure_same_tenant(principal: Principal, tenant_id: str) -> None:
    # Keep admin endpoints scoped to the caller's tenant.
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant scope does not match admin key")


def _to_plan_response(tenant_id: str, plan: PlanLimit | None) -> PlanLimitResponse:
    # Return default quota settings when no plan limits are configured.
    return PlanLimitResponse(
        tenant_id=tenant_id,
        daily_requests_limit=plan.daily_requests_limit if plan else None,
        monthly_requests_limit=plan.monthly_requests_limit if plan else None,
        daily_tokens_limit=plan.daily_tokens_limit if plan else None,
        monthly_tokens_limit=plan.monthly_tokens_limit if plan else None,
        soft_cap_ratio=plan.soft_cap_ratio if plan else 0.8,
        hard_cap_enabled=plan.hard_cap_enabled if plan else True,
    )


@router.get("/quotas/{tenant_id}")
async def get_quota_limits(
    tenant_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PlanLimitResponse:
    # Allow admins to view quota limits for their tenant.
    _ensure_same_tenant(principal, tenant_id)
    try:
        result = await db.execute(select(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
        plan = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching quota limits") from exc
    return _to_plan_response(tenant_id, plan)


@router.patch("/quotas/{tenant_id}")
async def patch_quota_limits(
    tenant_id: str,
    payload: PlanLimitPatchRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PlanLimitResponse:
    # Allow admins to update quota limits for their tenant.
    _ensure_same_tenant(principal, tenant_id)
    try:
        result = await db.execute(select(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
        plan = result.scalar_one_or_none()
        if plan is None:
            plan = PlanLimit(tenant_id=tenant_id)
            db.add(plan)

        if payload.daily_requests_limit is not None:
            plan.daily_requests_limit = payload.daily_requests_limit
        if payload.monthly_requests_limit is not None:
            plan.monthly_requests_limit = payload.monthly_requests_limit
        if payload.daily_tokens_limit is not None:
            plan.daily_tokens_limit = payload.daily_tokens_limit
        if payload.monthly_tokens_limit is not None:
            plan.monthly_tokens_limit = payload.monthly_tokens_limit
        if payload.soft_cap_ratio is not None:
            plan.soft_cap_ratio = payload.soft_cap_ratio
        if payload.hard_cap_enabled is not None:
            plan.hard_cap_enabled = payload.hard_cap_enabled

        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while updating quota limits") from exc

    return _to_plan_response(tenant_id, plan)


@router.get("/usage/{tenant_id}")
async def get_usage_summary(
    tenant_id: str,
    period: str = Query(default="day", pattern="^(day|month)$"),
    start: date = Query(...),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> UsageSummaryResponse:
    # Return usage summaries for day/month periods for admin review.
    _ensure_same_tenant(principal, tenant_id)
    period_start = parse_period_start(period, start)
    try:
        result = await db.execute(
            select(UsageCounter).where(
                UsageCounter.tenant_id == tenant_id,
                UsageCounter.period_type == period,
                UsageCounter.period_start == period_start,
            )
        )
        counter = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching usage") from exc

    return UsageSummaryResponse(
        tenant_id=tenant_id,
        period_type=period,
        period_start=period_start.isoformat(),
        requests_count=int(counter.requests_count) if counter else 0,
        estimated_tokens_count=counter.estimated_tokens_count if counter else None,
    )
