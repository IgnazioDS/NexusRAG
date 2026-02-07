from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from nexusrag.domain.models import UsageCounter
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.quota import QuotaService, _billing_signature, parse_period_start


@dataclass
class _Principal:
    # Minimal principal for quota service unit tests.
    tenant_id: str
    api_key_id: str
    role: str


@pytest.mark.asyncio
async def test_quota_rollover_creates_new_period_rows() -> None:
    tenant_id = f"t-quota-{uuid4().hex}"
    principal = _Principal(tenant_id=tenant_id, api_key_id="key", role="admin")

    day_one = datetime(2026, 2, 7, 12, 0, tzinfo=timezone.utc)
    day_two = datetime(2026, 2, 8, 12, 0, tzinfo=timezone.utc)
    next_month = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    service_day_one = QuotaService(time_provider=lambda: day_one)
    service_day_two = QuotaService(time_provider=lambda: day_two)
    service_next_month = QuotaService(time_provider=lambda: next_month)

    try:
        async with SessionLocal() as session:
            await service_day_one.check_and_consume_quota(
                session=session, principal=principal, estimated_cost=1
            )
        async with SessionLocal() as session:
            await service_day_two.check_and_consume_quota(
                session=session, principal=principal, estimated_cost=1
            )
        async with SessionLocal() as session:
            await service_next_month.check_and_consume_quota(
                session=session, principal=principal, estimated_cost=1
            )

        async with SessionLocal() as session:
            day_start_one = parse_period_start("day", day_one.date())
            day_start_two = parse_period_start("day", day_two.date())
            month_start_feb = parse_period_start("month", day_one.date())
            month_start_mar = parse_period_start("month", next_month.date())

            day_rows = (
                await session.execute(
                    select(UsageCounter).where(
                        UsageCounter.tenant_id == tenant_id,
                        UsageCounter.period_type == "day",
                    )
                )
            ).scalars().all()
            month_rows = (
                await session.execute(
                    select(UsageCounter).where(
                        UsageCounter.tenant_id == tenant_id,
                        UsageCounter.period_type == "month",
                    )
                )
            ).scalars().all()

            assert any(row.period_start == day_start_one for row in day_rows)
            assert any(row.period_start == day_start_two for row in day_rows)
            assert any(row.period_start == month_start_feb for row in month_rows)
            assert any(row.period_start == month_start_mar for row in month_rows)
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(UsageCounter).where(UsageCounter.tenant_id == tenant_id))
            await session.commit()


def test_billing_signature_is_deterministic() -> None:
    payload = b"{\"event\":\"quota\"}"
    secret = "test-secret"
    signature = _billing_signature(secret, payload)
    assert signature == _billing_signature(secret, payload)
