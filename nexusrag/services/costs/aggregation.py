from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import UsageCostEvent


@dataclass(frozen=True)
class CostSummary:
    # Capture aggregate spend values for reporting responses.
    total_usd: Decimal
    by_component: dict[str, Decimal]
    by_provider: dict[str, Decimal]
    by_route_class: dict[str, Decimal]


def _utc_now() -> datetime:
    # Use UTC to align month boundaries across services.
    return datetime.now(timezone.utc)


def month_bounds(year_month: str) -> tuple[datetime, datetime]:
    # Parse YYYY-MM into a month start/end window for cost queries.
    year, month = (int(part) for part in year_month.split("-", 1))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def current_year_month(now: datetime | None = None) -> str:
    # Normalize the current month for snapshot keys.
    current = now or _utc_now()
    return f"{current.year:04d}-{current.month:02d}"


async def sum_costs(
    *,
    session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
) -> Decimal:
    # Sum cost_usd across the specified window for budget calculations.
    result = await session.execute(
        select(func.coalesce(func.sum(UsageCostEvent.cost_usd), 0)).where(
            UsageCostEvent.tenant_id == tenant_id,
            UsageCostEvent.occurred_at >= start,
            UsageCostEvent.occurred_at < end,
        )
    )
    value = result.scalar_one_or_none() or 0
    return Decimal(str(value))


async def breakdown_costs(
    *,
    session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
    by: str,
) -> dict[str, Decimal]:
    # Aggregate spend by a single dimension for breakdown endpoints.
    if by not in {"component", "provider", "route_class"}:
        return {}
    column = getattr(UsageCostEvent, by)
    result = await session.execute(
        select(column, func.coalesce(func.sum(UsageCostEvent.cost_usd), 0))
        .where(
            UsageCostEvent.tenant_id == tenant_id,
            UsageCostEvent.occurred_at >= start,
            UsageCostEvent.occurred_at < end,
        )
        .group_by(column)
    )
    breakdown: dict[str, Decimal] = {}
    for key, value in result.all():
        if key is None:
            continue
        breakdown[str(key)] = Decimal(str(value or 0))
    return breakdown


async def build_summary(
    *,
    session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
) -> CostSummary:
    # Aggregate spend totals plus component/provider/route-class splits.
    total = await sum_costs(session=session, tenant_id=tenant_id, start=start, end=end)
    by_component = await breakdown_costs(session=session, tenant_id=tenant_id, start=start, end=end, by="component")
    by_provider = await breakdown_costs(session=session, tenant_id=tenant_id, start=start, end=end, by="provider")
    by_route_class = await breakdown_costs(
        session=session, tenant_id=tenant_id, start=start, end=end, by="route_class"
    )
    return CostSummary(
        total_usd=total,
        by_component=by_component,
        by_provider=by_provider,
        by_route_class=by_route_class,
    )


async def timeseries(
    *,
    session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
    granularity: str,
) -> list[dict[str, Any]]:
    # Generate a time-bucketed spend series for dashboard charts.
    if granularity not in {"day", "hour"}:
        granularity = "day"
    bucket = func.date_trunc(granularity, UsageCostEvent.occurred_at)
    result = await session.execute(
        select(bucket, func.coalesce(func.sum(UsageCostEvent.cost_usd), 0))
        .where(
            UsageCostEvent.tenant_id == tenant_id,
            UsageCostEvent.occurred_at >= start,
            UsageCostEvent.occurred_at < end,
        )
        .group_by(bucket)
        .order_by(bucket.asc())
    )
    points: list[dict[str, Any]] = []
    for ts, value in result.all():
        if ts is None:
            continue
        if isinstance(ts, datetime):
            ts_value = ts.isoformat()
        else:
            ts_value = str(ts)
        points.append({"ts": ts_value, "value_usd": float(value or 0)})
    return points
