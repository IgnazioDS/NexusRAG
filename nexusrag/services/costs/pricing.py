from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import PricingCatalog


@dataclass(frozen=True)
class PricingRate:
    # Capture a stable pricing snapshot for deterministic cost calculations.
    provider: str
    component: str
    rate_type: str
    rate_value_usd: Decimal
    version: str
    effective_from: datetime
    effective_to: datetime | None


async def select_pricing_rate(
    *,
    session: AsyncSession,
    provider: str,
    component: str,
    rate_type: str,
    occurred_at: datetime,
) -> PricingRate | None:
    # Resolve a single active pricing rate for the given provider/component at time.
    result = await session.execute(
        select(PricingCatalog)
        .where(
            PricingCatalog.provider == provider,
            PricingCatalog.component == component,
            PricingCatalog.rate_type == rate_type,
            PricingCatalog.active.is_(True),
            PricingCatalog.effective_from <= occurred_at,
            or_(PricingCatalog.effective_to.is_(None), PricingCatalog.effective_to >= occurred_at),
        )
        .order_by(PricingCatalog.effective_from.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return PricingRate(
        provider=row.provider,
        component=row.component,
        rate_type=row.rate_type,
        rate_value_usd=Decimal(str(row.rate_value_usd)),
        version=row.version,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
    )


def rate_metadata(rate: PricingRate) -> dict[str, Any]:
    # Serialize a pricing snapshot for persistence alongside cost events.
    return {
        "provider": rate.provider,
        "component": rate.component,
        "rate_type": rate.rate_type,
        "rate_value_usd": str(rate.rate_value_usd),
        "version": rate.version,
        "effective_from": rate.effective_from.isoformat(),
        "effective_to": rate.effective_to.isoformat() if rate.effective_to else None,
    }
