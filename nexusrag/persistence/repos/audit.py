from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import AuditEvent


async def list_events(
    session: AsyncSession,
    *,
    tenant_id: str,
    event_type: str | None = None,
    outcome: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[AuditEvent]:
    # Scope all audit queries to a tenant to prevent cross-tenant leakage.
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    if resource_type:
        stmt = stmt.where(AuditEvent.resource_type == resource_type)
    if resource_id:
        stmt = stmt.where(AuditEvent.resource_id == resource_id)
    if occurred_from:
        stmt = stmt.where(AuditEvent.occurred_at >= occurred_from)
    if occurred_to:
        stmt = stmt.where(AuditEvent.occurred_at <= occurred_to)

    stmt = stmt.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_event_by_id(
    session: AsyncSession,
    *,
    tenant_id: str,
    event_id: int,
) -> AuditEvent | None:
    # Fetch a single audit event for a tenant-scoped investigation detail view.
    result = await session.execute(
        select(AuditEvent).where(AuditEvent.id == event_id, AuditEvent.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()
