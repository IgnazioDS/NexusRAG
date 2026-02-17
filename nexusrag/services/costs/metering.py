from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import UsageCostEvent
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.audit import record_event
from nexusrag.services.costs.pricing import PricingRate, rate_metadata, select_pricing_rate


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CostEstimate:
    # Return computed cost plus metadata used for budget guardrails and events.
    cost_usd: Decimal
    rate: PricingRate | None
    estimated: bool


def _utc_now() -> datetime:
    # Use UTC timestamps to keep cost events aligned with budgets.
    return datetime.now(timezone.utc)


def estimate_tokens(text: str, *, ratio: float) -> int:
    # Deterministically estimate token counts when provider metadata is missing.
    if not text:
        return 0
    return max(1, int(len(text) / max(ratio, 0.1)))


def _to_decimal(value: float | int | Decimal) -> Decimal:
    # Normalize numeric values to Decimal for consistent rounding.
    return value if isinstance(value, Decimal) else Decimal(str(value))


def calculate_cost(*, rate_type: str, rate_value_usd: Decimal, units: dict[str, Any]) -> Decimal:
    # Apply a unit-based pricing model to compute USD cost deterministically.
    if rate_type == "per_1k_tokens":
        tokens = _to_decimal(units.get("tokens", 0))
        return (tokens / Decimal("1000")) * rate_value_usd
    if rate_type == "per_char":
        chars = _to_decimal(units.get("chars", 0))
        return chars * rate_value_usd
    if rate_type == "per_mb":
        bytes_value = _to_decimal(units.get("bytes", 0))
        return (bytes_value / Decimal(str(1024 * 1024))) * rate_value_usd
    if rate_type == "per_request":
        requests = _to_decimal(units.get("requests", 1))
        return requests * rate_value_usd
    if rate_type == "per_second":
        seconds = _to_decimal(units.get("seconds", 0))
        return seconds * rate_value_usd
    return Decimal("0")


async def estimate_cost(
    *,
    session: AsyncSession,
    provider: str,
    component: str,
    rate_type: str,
    units: dict[str, Any],
    occurred_at: datetime | None = None,
) -> CostEstimate:
    # Resolve pricing and compute estimated cost for guardrail decisions.
    occurred = occurred_at or _utc_now()
    rate = await select_pricing_rate(
        session=session,
        provider=provider,
        component=component,
        rate_type=rate_type,
        occurred_at=occurred,
    )
    if rate is None:
        return CostEstimate(cost_usd=Decimal("0"), rate=None, estimated=True)
    return CostEstimate(
        cost_usd=calculate_cost(rate_type=rate.rate_type, rate_value_usd=rate.rate_value_usd, units=units),
        rate=rate,
        estimated=False,
    )


async def record_cost_event(
    *,
    session: AsyncSession | None,
    tenant_id: str,
    request_id: str | None,
    session_id: str | None,
    route_class: str,
    component: str,
    provider: str,
    units: dict[str, Any],
    rate_type: str,
    occurred_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    emit_event: bool = True,
) -> Decimal:
    # Persist a cost event without blocking the caller on failures.
    occurred = occurred_at or _utc_now()
    settings = get_settings()
    estimated = False

    async def _write(session_to_use: AsyncSession) -> Decimal:
        nonlocal estimated
        estimate = await estimate_cost(
            session=session_to_use,
            provider=provider,
            component=component,
            rate_type=rate_type,
            units=units,
            occurred_at=occurred,
        )
        estimated = estimate.estimated
        cost_usd = max(Decimal("0"), estimate.cost_usd)
        event = UsageCostEvent(
            id=uuid4().hex,
            tenant_id=tenant_id,
            request_id=request_id,
            session_id=session_id,
            route_class=route_class,
            component=component,
            provider=provider,
            units_json=units,
            unit_cost_json=rate_metadata(estimate.rate) if estimate.rate else None,
            cost_usd=float(cost_usd),
            occurred_at=occurred,
            metadata_json=metadata or {},
        )
        session_to_use.add(event)
        await session_to_use.commit()
        if emit_event:
            await record_event(
                session=session_to_use,
                tenant_id=tenant_id,
                actor_type="system",
                actor_id=None,
                actor_role=None,
                event_type="cost.event.recorded",
                outcome="success",
                resource_type="usage_cost_event",
                resource_id=event.id,
                metadata={
                    "component": component,
                    "provider": provider,
                    "cost_usd": str(cost_usd),
                    "estimated": estimated,
                },
                commit=True,
                best_effort=True,
            )
        if estimate.rate is None:
            await record_event(
                session=session_to_use,
                tenant_id=tenant_id,
                actor_type="system",
                actor_id=None,
                actor_role=None,
                event_type="cost.metering.degraded",
                outcome="failure",
                resource_type="pricing",
                resource_id=None,
                metadata={
                    "component": component,
                    "provider": provider,
                    "rate_type": rate_type,
                    "reason": "pricing_not_found",
                },
                commit=True,
                best_effort=True,
            )
        return cost_usd

    try:
        if session is None:
            async with SessionLocal() as local_session:
                return await _write(local_session)
        return await _write(session)
    except SQLAlchemyError as exc:
        logger.warning("cost_event_write_failed tenant=%s component=%s", tenant_id, component, exc_info=exc)
        await record_event(
            session=None,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type="cost.metering.degraded",
            outcome="failure",
            resource_type="usage_cost_event",
            resource_id=None,
            metadata={
                "component": component,
                "provider": provider,
                "rate_type": rate_type,
                "estimated": True,
                "reason": "db_write_failed",
            },
            commit=True,
            best_effort=True,
        )
        return Decimal("0")
