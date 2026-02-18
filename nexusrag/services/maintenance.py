from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from nexusrag.services.backup import (
    create_backup_job,
    prune_backups,
    run_backup_job,
    run_restore_drill,
)
from nexusrag.services.compliance.maintenance import (
    compliance_bundle_periodic,
    compliance_evaluate_scheduled,
    compliance_prune_old_evidence,
)

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    AuditEvent,
    BackupJob,
    IdempotencyRecord,
    LegalHold,
    NotificationAttempt,
    NotificationJob,
    RetentionRun,
    UiAction,
    UsageCounter,
)
from nexusrag.services.governance import LEGAL_HOLD_SCOPE_BACKUP_SET, run_retention_for_tenant


MaintenanceTask = Literal[
    "prune_idempotency",
    "prune_audit",
    "cleanup_actions",
    "prune_usage",
    "prune_retention_all",
    "backup_create_scheduled",
    "backup_prune_retention",
    "restore_drill_scheduled",
    "compliance_evaluate_scheduled",
    "compliance_bundle_periodic",
    "compliance_prune_old_evidence",
]


async def prune_idempotency(session: AsyncSession) -> int:
    # Remove expired idempotency records to keep storage bounded.
    result = await session.execute(
        delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < datetime.now(timezone.utc))
    )
    return result.rowcount or 0


async def prune_audit_events(session: AsyncSession) -> int:
    # Remove audit events beyond the retention window.
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.audit_retention_days)
    result = await session.execute(delete(AuditEvent).where(AuditEvent.occurred_at < cutoff))
    return result.rowcount or 0


async def cleanup_ui_actions(session: AsyncSession) -> int:
    # Remove stale UI action rows after the retention window.
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.ui_action_retention_days)
    result = await session.execute(delete(UiAction).where(UiAction.created_at < cutoff))
    return result.rowcount or 0


async def prune_usage_counters(session: AsyncSession) -> int:
    # Drop old usage counters once they fall outside the rollup window.
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.usage_counter_retention_days)
    result = await session.execute(delete(UsageCounter).where(UsageCounter.period_start < cutoff))
    return result.rowcount or 0


async def prune_notification_history(session: AsyncSession) -> int:
    # Delete only terminal notification rows after retention to preserve active delivery state.
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.ui_action_retention_days)
    terminal_statuses = ("delivered", "dlq")
    job_ids = (
        await session.execute(
            select(NotificationJob.id).where(
                NotificationJob.status.in_(terminal_statuses),
                NotificationJob.updated_at < cutoff,
            )
        )
    ).scalars().all()
    if not job_ids:
        return 0
    # Remove immutable attempts first to satisfy FK constraints without requiring ON DELETE CASCADE.
    attempts_deleted = await session.execute(delete(NotificationAttempt).where(NotificationAttempt.job_id.in_(job_ids)))
    jobs_deleted = await session.execute(delete(NotificationJob).where(NotificationJob.id.in_(job_ids)))
    return int(attempts_deleted.rowcount or 0) + int(jobs_deleted.rowcount or 0)


async def backup_create_scheduled(session: AsyncSession) -> int:
    # Run a scheduled DR backup job for compliance requirements.
    settings = get_settings()
    if not settings.backup_enabled:
        return 0
    job = await create_backup_job(
        session,
        backup_type="all",
        created_by_actor_id=None,
        tenant_scope=None,
        metadata={"source": "scheduler"},
    )
    await run_backup_job(
        session=session,
        job=job,
        backup_type="all",
        output_dir=Path(settings.backup_local_dir),
        actor_type="system",
        tenant_id=None,
        actor_id=None,
        actor_role=None,
        request_id=None,
    )
    return 0


async def backup_prune_retention(session: AsyncSession) -> int:
    # Prune backup artifacts beyond retention to control storage costs.
    settings = get_settings()
    now = datetime.now(timezone.utc)
    hold_scope_ids = set(
        (
            await session.execute(
                select(LegalHold.scope_id).where(
                    LegalHold.scope_type == LEGAL_HOLD_SCOPE_BACKUP_SET,
                    LegalHold.is_active.is_(True),
                    or_(LegalHold.expires_at.is_(None), LegalHold.expires_at > now),
                    LegalHold.scope_id.is_not(None),
                )
            )
        ).scalars().all()
    )
    return await prune_backups(
        session=session,
        base_dir=Path(settings.backup_local_dir),
        retention_days=settings.backup_retention_days,
        held_backup_scope_ids=hold_scope_ids,
    )


async def restore_drill_scheduled(session: AsyncSession) -> int:
    # Execute scheduled restore drills to validate backup integrity.
    settings = get_settings()
    if not settings.backup_enabled:
        return 0
    latest_backup = (
        await session.execute(
            select(BackupJob)
            .where(BackupJob.status == "succeeded")
            .order_by(BackupJob.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_backup is None or not latest_backup.manifest_uri:
        return 0
    await run_restore_drill(
        session=session,
        manifest_uri=latest_backup.manifest_uri,
        actor_type="system",
        tenant_id=None,
        actor_id=None,
        actor_role=None,
        request_id=None,
    )
    return 0


async def prune_retention_all(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> dict[str, int]:
    # Run all retention-oriented tasks in one transaction to produce a single auditable result.
    idempotency_deleted = await prune_idempotency(session)
    audit_deleted = await prune_audit_events(session)
    usage_deleted = await prune_usage_counters(session)
    actions_deleted = await cleanup_ui_actions(session)
    notifications_deleted = await prune_notification_history(session)
    governance_run = await run_retention_for_tenant(
        session=session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
    )
    return {
        "prune_idempotency": idempotency_deleted,
        "prune_audit": audit_deleted,
        "prune_usage": usage_deleted,
        "cleanup_actions": actions_deleted,
        "cleanup_notifications": notifications_deleted,
        "governance_items": int((governance_run.report_json or {}).get("summary", {}).get("counts", {}).get("deleted", 0)),
    }


async def record_retention_run(
    session: AsyncSession,
    *,
    tenant_id: str | None,
    task: str,
    outcome: str,
    details_json: dict[str, object] | None,
) -> RetentionRun:
    # Persist retention maintenance execution metadata for compliance status reporting.
    row = RetentionRun(
        tenant_id=tenant_id,
        task=task,
        outcome=outcome,
        details_json=details_json,
    )
    session.add(row)
    await session.flush()
    return row
