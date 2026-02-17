from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from nexusrag.domain.models import (
    AuditEvent,
    ChargebackReport,
    PricingCatalog,
    TenantBudget,
    TenantBudgetSnapshot,
    UsageCostEvent,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.costs.aggregation import build_summary, breakdown_costs
from nexusrag.services.costs.budget_guardrails import evaluate_budget_guardrail
from nexusrag.services.costs.metering import estimate_tokens
from nexusrag.services.costs.pricing import select_pricing_rate


@pytest.mark.asyncio
async def test_pricing_lookup_prefers_latest_rate() -> None:
    provider = f"internal-test-{uuid4().hex}"
    component = "llm"
    rate_type = "per_1k_tokens"
    now = datetime.now(timezone.utc)
    older = now - timedelta(days=10)
    newer = now - timedelta(days=2)
    try:
        async with SessionLocal() as session:
            session.add_all(
                [
                    PricingCatalog(
                        id=uuid4().hex,
                        version="v1",
                        provider=provider,
                        component=component,
                        rate_type=rate_type,
                        rate_value_usd=1.0,
                        effective_from=older,
                        effective_to=None,
                        active=True,
                        metadata_json=None,
                    ),
                    PricingCatalog(
                        id=uuid4().hex,
                        version="v2",
                        provider=provider,
                        component=component,
                        rate_type=rate_type,
                        rate_value_usd=2.0,
                        effective_from=newer,
                        effective_to=None,
                        active=True,
                        metadata_json=None,
                    ),
                ]
            )
            await session.commit()

            rate = await select_pricing_rate(
                session=session,
                provider=provider,
                component=component,
                rate_type=rate_type,
                occurred_at=now,
            )
            assert rate is not None
            assert rate.version == "v2"
            assert rate.rate_value_usd == Decimal("2.0")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(PricingCatalog).where(PricingCatalog.provider == provider))
            await session.commit()


def test_estimate_tokens_is_deterministic() -> None:
    text = "Cost estimation should be stable."
    assert estimate_tokens(text, ratio=4.0) == estimate_tokens(text, ratio=4.0)


@pytest.mark.asyncio
async def test_budget_guardrail_decision_matrix() -> None:
    tenant_id = f"t-budget-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    try:
        async with SessionLocal() as session:
            session.add(
                TenantBudget(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    monthly_budget_usd=100,
                    warn_ratio=0.8,
                    enforce_hard_cap=True,
                    hard_cap_mode="block",
                    current_month_override_usd=None,
                )
            )
            session.add(
                UsageCostEvent(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    request_id=None,
                    session_id=None,
                    route_class="run",
                    component="llm",
                    provider="internal",
                    units_json={"tokens": 1000},
                    unit_cost_json=None,
                    cost_usd=70.0,
                    occurred_at=now,
                    metadata_json={"estimated": True},
                )
            )
            await session.commit()

            decision_ok = await evaluate_budget_guardrail(
                session=session,
                tenant_id=tenant_id,
                projected_cost_usd=Decimal("5"),
                estimated=True,
                actor_id=None,
                actor_role=None,
                route_class="run",
                request_id=None,
                request=None,
                operation="run",
                enforce=True,
                raise_on_block=False,
            )
            assert decision_ok.status == "ok"
            assert decision_ok.allowed is True

            decision_warn = await evaluate_budget_guardrail(
                session=session,
                tenant_id=tenant_id,
                projected_cost_usd=Decimal("15"),
                estimated=True,
                actor_id=None,
                actor_role=None,
                route_class="run",
                request_id=None,
                request=None,
                operation="run",
                enforce=True,
                raise_on_block=False,
            )
            assert decision_warn.status == "warn"

            decision_block = await evaluate_budget_guardrail(
                session=session,
                tenant_id=tenant_id,
                projected_cost_usd=Decimal("40"),
                estimated=True,
                actor_id=None,
                actor_role=None,
                route_class="run",
                request_id=None,
                request=None,
                operation="run",
                enforce=True,
                raise_on_block=False,
            )
            assert decision_block.status == "capped"
            assert decision_block.allowed is False

            session.add(
                TenantBudget(
                    id=uuid4().hex,
                    tenant_id=f"{tenant_id}-degrade",
                    monthly_budget_usd=10,
                    warn_ratio=0.8,
                    enforce_hard_cap=True,
                    hard_cap_mode="degrade",
                    current_month_override_usd=None,
                )
            )
            await session.commit()

            decision_degrade = await evaluate_budget_guardrail(
                session=session,
                tenant_id=f"{tenant_id}-degrade",
                projected_cost_usd=Decimal("20"),
                estimated=True,
                actor_id=None,
                actor_role=None,
                route_class="run",
                request_id=None,
                request=None,
                operation="run",
                enforce=True,
                raise_on_block=False,
            )
            assert decision_degrade.status == "degraded"
            assert decision_degrade.allowed is True
            assert decision_degrade.degrade_actions is not None
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(TenantBudgetSnapshot).where(TenantBudgetSnapshot.tenant_id.like(f"{tenant_id}%")))
            await session.execute(delete(TenantBudget).where(TenantBudget.tenant_id.like(f"{tenant_id}%")))
            await session.execute(delete(UsageCostEvent).where(UsageCostEvent.tenant_id.like(f"{tenant_id}%")))
            await session.execute(delete(AuditEvent).where(AuditEvent.tenant_id.like(f"{tenant_id}%")))
            await session.commit()


@pytest.mark.asyncio
async def test_breakdown_aggregation_correctness() -> None:
    tenant_id = f"t-breakdown-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    try:
        async with SessionLocal() as session:
            session.add_all(
                [
                    UsageCostEvent(
                        id=uuid4().hex,
                        tenant_id=tenant_id,
                        request_id=None,
                        session_id=None,
                        route_class="run",
                        component="llm",
                        provider="internal",
                        units_json={"tokens": 1000},
                        unit_cost_json=None,
                        cost_usd=1.5,
                        occurred_at=now,
                        metadata_json=None,
                    ),
                    UsageCostEvent(
                        id=uuid4().hex,
                        tenant_id=tenant_id,
                        request_id=None,
                        session_id=None,
                        route_class="ingest",
                        component="storage",
                        provider="internal",
                        units_json={"bytes": 2048},
                        unit_cost_json=None,
                        cost_usd=0.5,
                        occurred_at=now,
                        metadata_json=None,
                    ),
                ]
            )
            await session.commit()

            start = now - timedelta(days=1)
            end = now + timedelta(days=1)
            summary = await build_summary(session=session, tenant_id=tenant_id, start=start, end=end)
            assert summary.total_usd == Decimal("2.0")
            assert summary.by_component["llm"] == Decimal("1.5")
            assert summary.by_component["storage"] == Decimal("0.5")
            breakdown = await breakdown_costs(
                session=session,
                tenant_id=tenant_id,
                start=start,
                end=end,
                by="route_class",
            )
            assert breakdown["run"] == Decimal("1.5")
            assert breakdown["ingest"] == Decimal("0.5")
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(UsageCostEvent).where(UsageCostEvent.tenant_id == tenant_id))
            await session.commit()


@pytest.mark.asyncio
async def test_chargeback_report_math() -> None:
    tenant_id = f"t-chargeback-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    try:
        async with SessionLocal() as session:
            session.add(
                UsageCostEvent(
                    id=uuid4().hex,
                    tenant_id=tenant_id,
                    request_id=None,
                    session_id=None,
                    route_class="run",
                    component="llm",
                    provider="internal",
                    units_json={"tokens": 500},
                    unit_cost_json=None,
                    cost_usd=3.25,
                    occurred_at=now,
                    metadata_json=None,
                )
            )
            await session.commit()

            start = now - timedelta(days=1)
            end = now + timedelta(days=1)
            summary = await build_summary(session=session, tenant_id=tenant_id, start=start, end=end)
            report = ChargebackReport(
                id=uuid4().hex,
                tenant_id=tenant_id,
                period_start=start,
                period_end=end,
                currency="USD",
                total_usd=float(summary.total_usd),
                breakdown_json={
                    "component": {k: float(v) for k, v in summary.by_component.items()},
                    "provider": {k: float(v) for k, v in summary.by_provider.items()},
                    "route_class": {k: float(v) for k, v in summary.by_route_class.items()},
                },
                generated_at=now,
                generated_by="test",
            )
            assert report.total_usd == 3.25
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(UsageCostEvent).where(UsageCostEvent.tenant_id == tenant_id))
            await session.commit()
