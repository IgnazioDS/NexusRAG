from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import calendar
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import TenantBudget, TenantBudgetSnapshot
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.costs.aggregation import current_year_month, sum_costs


@dataclass(frozen=True)
class DegradeActions:
    # Describe downgrade actions applied when budgets are capped in degrade mode.
    disable_audio: bool = False
    top_k: int | None = None
    max_output_tokens: int | None = None
    ingest_chunk_size: int | None = None
    ingest_chunk_overlap: int | None = None


@dataclass(frozen=True)
class BudgetDecision:
    # Normalize guardrail decisions for response headers and SSE events.
    allowed: bool
    status: str
    budget_usd: Decimal | None
    spend_usd: Decimal
    remaining_usd: Decimal | None
    estimated: bool
    degrade_actions: DegradeActions | None


def _utc_now() -> datetime:
    # Use UTC timestamps to keep budgets aligned across services.
    return datetime.now(timezone.utc)


def _budget_error(detail: dict[str, Any]) -> HTTPException:
    # Return a stable 402 for budget enforcement failures.
    return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)


async def _load_budget(session: AsyncSession, tenant_id: str) -> TenantBudget | None:
    # Fetch the current tenant budget configuration.
    result = await session.execute(
        select(TenantBudget).where(TenantBudget.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


def _effective_budget(budget: TenantBudget, *, year_month: str) -> Decimal:
    # Apply current-month overrides when present.
    if budget.current_month_override_usd is not None:
        return Decimal(str(budget.current_month_override_usd))
    return Decimal(str(budget.monthly_budget_usd))


def _forecast(spend_usd: Decimal, now: datetime) -> Decimal | None:
    # Simple linear forecast based on current month progress.
    day = max(1, now.day)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    return (spend_usd / Decimal(day)) * Decimal(days_in_month)


async def _upsert_snapshot(
    *,
    session: AsyncSession,
    tenant_id: str,
    year_month: str,
    budget_usd: Decimal,
    spend_usd: Decimal,
    status: str,
    warn_triggered: bool,
    cap_triggered: bool,
    now: datetime,
) -> None:
    # Persist budget snapshots so chargeback reports can explain enforcement.
    result = await session.execute(
        select(TenantBudgetSnapshot).where(
            TenantBudgetSnapshot.tenant_id == tenant_id,
            TenantBudgetSnapshot.year_month == year_month,
        )
    )
    snapshot = result.scalar_one_or_none()
    forecast = _forecast(spend_usd, now)
    if snapshot is None:
        snapshot = TenantBudgetSnapshot(
            id=f"{tenant_id}:{year_month}",
            tenant_id=tenant_id,
            year_month=year_month,
            budget_usd=float(budget_usd),
            spend_usd=float(spend_usd),
            forecast_usd=float(forecast) if forecast is not None else None,
            warn_triggered_at=now if warn_triggered else None,
            cap_triggered_at=now if cap_triggered else None,
            status=status,
            computed_at=now,
        )
        session.add(snapshot)
        await session.commit()
        return

    snapshot.budget_usd = float(budget_usd)
    snapshot.spend_usd = float(spend_usd)
    snapshot.forecast_usd = float(forecast) if forecast is not None else None
    snapshot.status = status
    snapshot.computed_at = now
    if warn_triggered and snapshot.warn_triggered_at is None:
        snapshot.warn_triggered_at = now
    if cap_triggered and snapshot.cap_triggered_at is None:
        snapshot.cap_triggered_at = now
    await session.commit()


async def evaluate_budget_guardrail(
    *,
    session: AsyncSession,
    tenant_id: str,
    projected_cost_usd: Decimal,
    estimated: bool,
    actor_id: str | None,
    actor_role: str | None,
    route_class: str,
    request_id: str | None,
    request: Any | None,
    operation: str,
    enforce: bool = True,
    raise_on_block: bool = True,
) -> BudgetDecision:
    # Evaluate budgets before expensive operations and emit audit events.
    settings = get_settings()
    now = _utc_now()
    if not settings.cost_governance_enabled:
        return BudgetDecision(
            allowed=True,
            status="ok",
            budget_usd=None,
            spend_usd=Decimal("0"),
            remaining_usd=None,
            estimated=estimated,
            degrade_actions=None,
        )

    year_month = current_year_month(now)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        month_end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)

    spend_usd = await sum_costs(session=session, tenant_id=tenant_id, start=month_start, end=month_end)
    budget = await _load_budget(session, tenant_id)
    if budget is None:
        return BudgetDecision(
            allowed=True,
            status="ok",
            budget_usd=None,
            spend_usd=spend_usd,
            remaining_usd=None,
            estimated=estimated,
            degrade_actions=None,
        )

    budget_usd = _effective_budget(budget, year_month=year_month)
    if budget_usd <= 0:
        return BudgetDecision(
            allowed=True,
            status="ok",
            budget_usd=budget_usd,
            spend_usd=spend_usd,
            remaining_usd=None,
            estimated=estimated,
            degrade_actions=None,
        )

    projected_spend = spend_usd + projected_cost_usd
    warn_ratio = Decimal(str(budget.warn_ratio or settings.cost_default_warn_ratio))
    warn_threshold = budget_usd * warn_ratio
    warn_triggered = projected_spend >= warn_threshold
    cap_triggered = projected_spend >= budget_usd
    enforce_cap = bool(budget.enforce_hard_cap and enforce)

    status_value = "ok"
    allowed = True
    degrade_actions: DegradeActions | None = None

    if cap_triggered and enforce_cap:
        if (budget.hard_cap_mode or settings.cost_default_hard_cap_mode) == "degrade":
            status_value = "degraded"
            degrade_actions = DegradeActions(
                disable_audio=settings.cost_degrade_enable_tts_disable,
                top_k=settings.cost_degrade_min_top_k,
                max_output_tokens=settings.cost_degrade_max_output_tokens,
            )
        else:
            status_value = "capped"
            allowed = False
    elif warn_triggered:
        status_value = "warn"

    remaining = max(Decimal("0"), budget_usd - projected_spend)

    snapshot_status = "capped" if cap_triggered and enforce_cap else ("warn" if warn_triggered else "ok")
    await _upsert_snapshot(
        session=session,
        tenant_id=tenant_id,
        year_month=year_month,
        budget_usd=budget_usd,
        spend_usd=projected_spend,
        status=snapshot_status,
        warn_triggered=warn_triggered,
        cap_triggered=cap_triggered and enforce_cap,
        now=now,
    )

    request_ctx = get_request_context(request)
    if warn_triggered:
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key" if actor_id else "system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="cost.warn.triggered",
            outcome="success",
            resource_type=operation,
            resource_id=request_id,
            request_id=request_ctx.get("request_id"),
            ip_address=request_ctx.get("ip_address"),
            user_agent=request_ctx.get("user_agent"),
            metadata={
                "budget_usd": str(budget_usd),
                "spend_usd": str(projected_spend),
                "route_class": route_class,
            },
            commit=True,
            best_effort=True,
        )
    if cap_triggered and enforce_cap:
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key" if actor_id else "system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="cost.cap.triggered",
            outcome="failure" if not allowed else "success",
            resource_type=operation,
            resource_id=request_id,
            request_id=request_ctx.get("request_id"),
            ip_address=request_ctx.get("ip_address"),
            user_agent=request_ctx.get("user_agent"),
            metadata={
                "budget_usd": str(budget_usd),
                "spend_usd": str(projected_spend),
                "hard_cap_mode": budget.hard_cap_mode or settings.cost_default_hard_cap_mode,
                "route_class": route_class,
            },
            commit=True,
            best_effort=True,
        )
    if status_value == "degraded":
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key" if actor_id else "system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="cost.degrade.applied",
            outcome="success",
            resource_type=operation,
            resource_id=request_id,
            request_id=request_ctx.get("request_id"),
            ip_address=request_ctx.get("ip_address"),
            user_agent=request_ctx.get("user_agent"),
            metadata={
                "budget_usd": str(budget_usd),
                "spend_usd": str(projected_spend),
                "actions": degrade_actions.__dict__ if degrade_actions else {},
            },
            commit=True,
            best_effort=True,
        )

    decision = BudgetDecision(
        allowed=allowed,
        status=status_value,
        budget_usd=budget_usd,
        spend_usd=projected_spend,
        remaining_usd=remaining,
        estimated=estimated,
        degrade_actions=degrade_actions,
    )

    if not allowed and raise_on_block:
        raise _budget_error(
            {
                "code": "COST_BUDGET_EXCEEDED",
                "message": "Cost budget exceeded",
                "budget_usd": str(budget_usd),
                "spend_usd": str(projected_spend),
                "status": status_value,
            }
        )

    return decision


def cost_headers(decision: BudgetDecision) -> dict[str, str]:
    # Render cost budget headers for downstream responses.
    budget = decision.budget_usd
    remaining = decision.remaining_usd
    return {
        "X-Cost-Month-Budget-Usd": str(budget) if budget is not None else "0",
        "X-Cost-Month-Spend-Usd": str(decision.spend_usd),
        "X-Cost-Month-Remaining-Usd": str(remaining) if remaining is not None else "0",
        "X-Cost-Status": decision.status,
        "X-Cost-Estimated": "true" if decision.estimated else "false",
    }
