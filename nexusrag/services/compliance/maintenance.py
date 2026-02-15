from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import ControlEvaluation, EvidenceBundle, LegalHold
from nexusrag.services.audit import record_event
from nexusrag.services.compliance.control_engine import evaluate_all_controls
from nexusrag.services.compliance.evidence_collector import generate_evidence_bundle
from nexusrag.services.governance import LEGAL_HOLD_SCOPE_TENANT


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def compliance_evaluate_scheduled(session: AsyncSession) -> int:
    # Run scheduled compliance evaluations and emit audit evidence.
    settings = get_settings()
    if not settings.compliance_enabled:
        return 0
    results = await evaluate_all_controls(
        session,
        window_days=settings.compliance_default_window_days,
        tenant_scope=None,
    )
    await record_event(
        session=session,
        tenant_id=None,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="compliance.schedule.run",
        outcome="success",
        resource_type="compliance",
        resource_id="evaluation",
        metadata={"evaluated": len(results)},
        commit=True,
        best_effort=True,
    )
    return len(results)


async def compliance_bundle_periodic(session: AsyncSession) -> int:
    # Generate periodic evidence bundles for SOC 2 readiness.
    settings = get_settings()
    if not settings.compliance_enabled:
        return 0
    period_end = _utc_now()
    period_start = period_end - timedelta(days=settings.compliance_default_window_days)
    await generate_evidence_bundle(
        session,
        bundle_type="soc2_periodic",
        period_start=period_start,
        period_end=period_end,
        tenant_scope=None,
        generated_by_actor_id=None,
    )
    await record_event(
        session=session,
        tenant_id=None,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="compliance.bundle.generated",
        outcome="success",
        resource_type="evidence_bundle",
        resource_id="soc2_periodic",
        metadata={"period_start": period_start.isoformat(), "period_end": period_end.isoformat()},
        commit=True,
        best_effort=True,
    )
    return 1


async def compliance_prune_old_evidence(session: AsyncSession) -> int:
    # Prune compliance evidence beyond retention while honoring legal holds.
    settings = get_settings()
    if not settings.compliance_enabled:
        return 0
    cutoff = _utc_now() - timedelta(days=settings.compliance_evidence_retention_days)
    hold = (
        await session.execute(
            select(LegalHold).where(
                LegalHold.scope_type == LEGAL_HOLD_SCOPE_TENANT,
                LegalHold.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if hold is not None:
        # Skip pruning if an active tenant-wide legal hold exists.
        return 0
    deleted_evals = await session.execute(
        delete(ControlEvaluation).where(ControlEvaluation.evaluated_at < cutoff)
    )
    deleted_bundles = await session.execute(
        delete(EvidenceBundle).where(EvidenceBundle.generated_at.is_not(None), EvidenceBundle.generated_at < cutoff)
    )
    deleted_total = (deleted_evals.rowcount or 0) + (deleted_bundles.rowcount or 0)
    await record_event(
        session=session,
        tenant_id=None,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="compliance.evidence.pruned",
        outcome="success",
        resource_type="compliance",
        resource_id="evidence",
        metadata={"deleted": deleted_total, "cutoff": cutoff.isoformat()},
        commit=True,
        best_effort=True,
    )
    return deleted_total
