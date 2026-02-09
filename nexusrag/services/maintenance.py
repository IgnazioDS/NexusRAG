from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import AuditEvent, IdempotencyRecord, UiAction, UsageCounter


MaintenanceTask = Literal["prune_idempotency", "prune_audit", "cleanup_actions", "prune_usage"]


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
