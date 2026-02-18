from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from nexusrag.domain.models import AlertEvent, AlertRule, IncidentTimelineEvent, OpsIncident
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.operability.alerts import _evaluate_single_rule, evaluate_alert_rules
from nexusrag.services.operability.incidents import open_incident_for_alert


@pytest.mark.asyncio
async def test_rule_parser_threshold_handling() -> None:
    # Verify comparator parsing remains deterministic for threshold edits.
    rule = AlertRule(
        rule_id=f"r-{uuid4().hex}",
        tenant_id="t-unit-alert",
        name="Threshold",
        severity="high",
        enabled=True,
        source="error.rate",
        expression_json={"metric": "error.rate", "operator": "gte"},
        window="5m",
        thresholds_json={"value": 0.05},
    )
    triggered, actual, threshold, reason = _evaluate_single_rule(rule, {"error.rate": 0.08})
    assert triggered is True
    assert actual == 0.08
    assert threshold == 0.05
    assert "error.rate gte 0.05" in reason


@pytest.mark.asyncio
async def test_alert_evaluator_triggers_from_seeded_metrics(monkeypatch) -> None:
    tenant_id = f"t-unit-alert-{uuid4().hex}"
    try:
        async with SessionLocal() as session:
            session.add(
                AlertRule(
                    rule_id=f"{tenant_id}:error_rate",
                    tenant_id=tenant_id,
                    name="Error rate spike",
                    severity="high",
                    enabled=True,
                    source="error.rate",
                    expression_json={"metric": "error.rate", "operator": "gte"},
                    window="5m",
                    thresholds_json={"value": 0.01},
                )
            )
            await session.commit()

            async def _metrics_stub(*, session, tenant_id, window):  # type: ignore[override]
                return {"error.rate": 0.2}

            from nexusrag.services.operability import alerts as alerts_module

            monkeypatch.setattr(alerts_module, "_collect_metrics", _metrics_stub)
            rows = await evaluate_alert_rules(
                session=session,
                tenant_id=tenant_id,
                window="5m",
                actor_id="tester",
                actor_role="admin",
                request_id="req-unit",
            )
            assert rows
            assert rows[0]["source"] == "error.rate"
            assert rows[0]["status"] == "triggered"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(AlertEvent).where(AlertEvent.tenant_id == tenant_id))
            await session.execute(delete(IncidentTimelineEvent).where(IncidentTimelineEvent.tenant_id == tenant_id))
            await session.execute(delete(OpsIncident).where(OpsIncident.tenant_id == tenant_id))
            await session.execute(delete(AlertRule).where(AlertRule.tenant_id == tenant_id))
            await session.commit()


@pytest.mark.asyncio
async def test_incident_dedupe_logic() -> None:
    tenant_id = f"t-unit-dedupe-{uuid4().hex}"
    try:
        async with SessionLocal() as session:
            first, first_created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="sla.shed.count",
                rule_id=None,
                severity="high",
                title="Shed",
                summary="first",
                details_json={"count": 1},
                actor_id="tester",
                actor_role="admin",
                request_id="req-1",
            )
            second, second_created = await open_incident_for_alert(
                session=session,
                tenant_id=tenant_id,
                category="sla.shed.count",
                rule_id=None,
                severity="critical",
                title="Shed",
                summary="second",
                details_json={"count": 2},
                actor_id="tester",
                actor_role="admin",
                request_id="req-2",
            )
            assert first_created is True
            assert second_created is False
            assert first.id == second.id
            assert second.severity == "critical"
            timeline = (
                await session.execute(
                    select(IncidentTimelineEvent).where(IncidentTimelineEvent.incident_id == first.id)
                )
            ).scalars().all()
            assert len(timeline) == 2
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(IncidentTimelineEvent).where(IncidentTimelineEvent.tenant_id == tenant_id))
            await session.execute(delete(OpsIncident).where(OpsIncident.tenant_id == tenant_id))
            await session.commit()
