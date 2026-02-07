from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.persistence.repos import audit as audit_repo


router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventResponse(BaseModel):
    id: int
    occurred_at: str
    tenant_id: str | None
    actor_type: str
    actor_id: str | None
    actor_role: str | None
    event_type: str
    outcome: str
    resource_type: str | None
    resource_id: str | None
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    metadata_json: dict[str, Any] | None
    error_code: str | None
    created_at: str


class AuditEventsPage(BaseModel):
    items: list[AuditEventResponse]
    next_offset: int | None


def _to_response(event) -> AuditEventResponse:
    # Serialize audit event datetimes to ISO 8601 for API clients.
    return AuditEventResponse(
        id=event.id,
        occurred_at=event.occurred_at.isoformat(),
        tenant_id=event.tenant_id,
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        actor_role=event.actor_role,
        event_type=event.event_type,
        outcome=event.outcome,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        request_id=event.request_id,
        ip_address=event.ip_address,
        user_agent=event.user_agent,
        metadata_json=event.metadata_json,
        error_code=event.error_code,
        created_at=event.created_at.isoformat(),
    )


@router.get("/events")
async def list_audit_events(
    tenant_id: str | None = None,
    event_type: str | None = None,
    outcome: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    occurred_from: datetime | None = Query(default=None, alias="from"),
    occurred_to: datetime | None = Query(default=None, alias="to"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> AuditEventsPage:
    # Enforce tenant scoping even for admins to avoid cross-tenant data access.
    scoped_tenant_id = tenant_id or principal.tenant_id
    if tenant_id and tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant scope does not match admin key")

    try:
        events = await audit_repo.list_events(
            db,
            tenant_id=scoped_tenant_id,
            event_type=event_type,
            outcome=outcome,
            resource_type=resource_type,
            resource_id=resource_id,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            offset=offset,
            limit=limit + 1,
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching audit events") from exc

    next_offset = None
    if len(events) > limit:
        events = events[:limit]
        next_offset = offset + limit

    return AuditEventsPage(items=[_to_response(event) for event in events], next_offset=next_offset)


@router.get("/events/{event_id}")
async def get_audit_event(
    event_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> AuditEventResponse:
    # Look up a single audit event within the admin's tenant scope.
    try:
        event = await audit_repo.get_event_by_id(db, tenant_id=principal.tenant_id, event_id=event_id)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching audit event") from exc
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return _to_response(event)
