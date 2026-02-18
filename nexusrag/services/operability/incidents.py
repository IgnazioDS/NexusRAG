from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import IncidentTimelineEvent, OpsIncident
from nexusrag.services.audit import record_event
from nexusrag.services.operability.notifications import send_operability_notification


_UNRESOLVED_STATUSES = ("open", "acknowledged", "assigned", "mitigating")


def _utc_now() -> datetime:
    # Use UTC timestamps to keep incident ordering deterministic across nodes.
    return datetime.now(timezone.utc)


def _severity_rank(value: str) -> int:
    # Normalize severity ordering so dedupe updates only escalate criticality.
    normalized = value.strip().lower()
    if normalized in {"sev1", "critical"}:
        return 4
    if normalized in {"sev2", "high"}:
        return 3
    if normalized in {"sev3", "medium"}:
        return 2
    return 1


async def _append_timeline_event(
    *,
    session: AsyncSession,
    incident: OpsIncident,
    event_type: str,
    actor_id: str | None,
    note: str | None,
    metadata: dict[str, Any] | None,
) -> IncidentTimelineEvent:
    # Persist immutable timeline rows for every operator and automation action.
    row = IncidentTimelineEvent(
        incident_id=incident.id,
        tenant_id=incident.tenant_id,
        event_type=event_type,
        actor_id=actor_id,
        note=note,
        metadata_json=metadata,
    )
    session.add(row)
    await session.flush()
    return row


async def open_incident_for_alert(
    *,
    session: AsyncSession,
    tenant_id: str,
    category: str,
    rule_id: str | None,
    severity: str,
    title: str,
    summary: str | None,
    details_json: dict[str, Any] | None,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> tuple[OpsIncident, bool]:
    # Deduplicate open incidents by tenant/category/rule so repeated alerts append timeline instead of fan-out.
    dedupe_key = f"{tenant_id}:{category}:{rule_id or 'none'}"
    existing = (
        await session.execute(
            select(OpsIncident)
            .where(
                OpsIncident.tenant_id == tenant_id,
                OpsIncident.dedupe_key == dedupe_key,
                OpsIncident.status.in_(_UNRESOLVED_STATUSES),
            )
            .order_by(OpsIncident.opened_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if _severity_rank(severity) > _severity_rank(existing.severity):
            existing.severity = severity
        existing.details_json = details_json
        await _append_timeline_event(
            session=session,
            incident=existing,
            event_type="incident.retriggered",
            actor_id=actor_id,
            note=summary,
            metadata={"category": category, "rule_id": rule_id},
        )
        await session.commit()
        await session.refresh(existing)
        await send_operability_notification(
            session=session,
            tenant_id=tenant_id,
            event_type="incident.updated",
            payload={"incident_id": existing.id, "category": category, "severity": existing.severity},
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
        )
        return existing, False

    incident = OpsIncident(
        id=uuid4().hex,
        tenant_id=tenant_id,
        category=category,
        rule_id=rule_id,
        severity=severity,
        status="open",
        title=title,
        summary=summary,
        dedupe_key=dedupe_key,
        opened_at=_utc_now(),
        details_json=details_json,
    )
    session.add(incident)
    await session.flush()
    await _append_timeline_event(
        session=session,
        incident=incident,
        event_type="incident.opened",
        actor_id=actor_id,
        note=summary,
        metadata={"category": category, "rule_id": rule_id},
    )
    await session.commit()
    await session.refresh(incident)

    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="system",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="incident.opened",
        outcome="failure",
        resource_type="incident",
        resource_id=incident.id,
        request_id=request_id,
        metadata={"category": category, "severity": severity, "rule_id": rule_id},
        commit=True,
        best_effort=True,
    )
    await send_operability_notification(
        session=session,
        tenant_id=tenant_id,
        event_type="incident.opened",
        payload={"incident_id": incident.id, "category": category, "severity": severity},
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
    )
    return incident, True


async def list_incidents(
    *,
    session: AsyncSession,
    tenant_id: str,
    status_filter: str | None = None,
) -> list[OpsIncident]:
    # Return newest incidents first for operator triage workflows.
    query = select(OpsIncident).where(OpsIncident.tenant_id == tenant_id)
    if status_filter:
        query = query.where(OpsIncident.status == status_filter)
    result = await session.execute(query.order_by(OpsIncident.opened_at.desc()))
    return list(result.scalars().all())


async def list_incident_timeline(
    *,
    session: AsyncSession,
    tenant_id: str,
    incident_id: str,
) -> list[IncidentTimelineEvent]:
    # Enforce tenant boundaries for incident timeline visibility.
    incident = await session.get(OpsIncident, incident_id)
    if incident is None or incident.tenant_id != tenant_id:
        return []
    rows = (
        await session.execute(
            select(IncidentTimelineEvent)
            .where(
                IncidentTimelineEvent.tenant_id == tenant_id,
                IncidentTimelineEvent.incident_id == incident_id,
            )
            .order_by(IncidentTimelineEvent.created_at.asc())
        )
    ).scalars().all()
    return list(rows)


async def acknowledge_incident(
    *,
    session: AsyncSession,
    tenant_id: str,
    incident_id: str,
    actor_id: str | None,
    actor_role: str | None,
    note: str | None,
    request_id: str | None,
) -> OpsIncident | None:
    # Track acknowledgement separately from assignment to preserve responder timelines.
    incident = await session.get(OpsIncident, incident_id)
    if incident is None or incident.tenant_id != tenant_id:
        return None
    incident.status = "acknowledged"
    incident.acknowledged_at = _utc_now()
    incident.acknowledged_by = actor_id
    await _append_timeline_event(
        session=session,
        incident=incident,
        event_type="incident.acknowledged",
        actor_id=actor_id,
        note=note,
        metadata={},
    )
    await session.commit()
    await session.refresh(incident)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="incident.acknowledged",
        outcome="success",
        resource_type="incident",
        resource_id=incident.id,
        request_id=request_id,
        metadata={},
        commit=True,
        best_effort=True,
    )
    return incident


async def assign_incident(
    *,
    session: AsyncSession,
    tenant_id: str,
    incident_id: str,
    actor_id: str | None,
    actor_role: str | None,
    assignee: str,
    note: str | None,
    request_id: str | None,
) -> OpsIncident | None:
    # Assignment keeps ownership explicit so escalations remain deterministic.
    incident = await session.get(OpsIncident, incident_id)
    if incident is None or incident.tenant_id != tenant_id:
        return None
    incident.status = "assigned"
    incident.assigned_to = assignee
    await _append_timeline_event(
        session=session,
        incident=incident,
        event_type="incident.assigned",
        actor_id=actor_id,
        note=note,
        metadata={"assigned_to": assignee},
    )
    await session.commit()
    await session.refresh(incident)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="incident.assigned",
        outcome="success",
        resource_type="incident",
        resource_id=incident.id,
        request_id=request_id,
        metadata={"assigned_to": assignee},
        commit=True,
        best_effort=True,
    )
    return incident


async def resolve_incident(
    *,
    session: AsyncSession,
    tenant_id: str,
    incident_id: str,
    actor_id: str | None,
    actor_role: str | None,
    note: str | None,
    request_id: str | None,
) -> OpsIncident | None:
    # Resolve incidents with immutable timestamps for post-incident evidence bundles.
    incident = await session.get(OpsIncident, incident_id)
    if incident is None or incident.tenant_id != tenant_id:
        return None
    incident.status = "resolved"
    incident.resolved_at = _utc_now()
    incident.resolved_by = actor_id
    await _append_timeline_event(
        session=session,
        incident=incident,
        event_type="incident.resolved",
        actor_id=actor_id,
        note=note,
        metadata={},
    )
    await session.commit()
    await session.refresh(incident)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="incident.resolved",
        outcome="success",
        resource_type="incident",
        resource_id=incident.id,
        request_id=request_id,
        metadata={},
        commit=True,
        best_effort=True,
    )
    return incident
