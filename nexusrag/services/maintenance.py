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
    UiAction,
    UsageCounter,
)
from nexusrag.services.governance import LEGAL_HOLD_SCOPE_BACKUP_SET


MaintenanceTask = Literal[
    "prune_idempotency",
    "prune_audit",
    "cleanup_actions",
    "prune_usage",
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
