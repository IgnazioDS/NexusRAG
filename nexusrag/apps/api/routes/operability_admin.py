from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, idempotency_key_header, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.services.entitlements import FEATURE_OPS_ADMIN, require_feature
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)
from nexusrag.services.operability import (
    acknowledge_incident,
    apply_operator_action,
    evaluate_alert_rules,
    list_alert_rules,
    list_incident_timeline,
    list_incidents,
    patch_alert_rule,
    resolve_incident,
)
from nexusrag.services.operability.incidents import assign_incident
from nexusrag.services.operability.notifications import (
    create_notification_destination,
    delete_notification_destination,
    get_notification_job,
    list_notification_destinations,
    list_notification_jobs,
    patch_notification_destination,
    retry_notification_job_now,
)

router = APIRouter(prefix="/admin", tags=["operability"], responses=DEFAULT_ERROR_RESPONSES)


class AlertRulePatchRequest(BaseModel):
    enabled: bool | None = None
    severity: str | None = None
    window: Literal["5m", "1h"] | None = None
    thresholds_json: dict[str, Any] | None = None


class IncidentAckRequest(BaseModel):
    note: str | None = None


class IncidentAssignRequest(BaseModel):
    assignee: str = Field(..., min_length=1, max_length=128)
    note: str | None = None


class IncidentResolveRequest(BaseModel):
    note: str | None = None


class FreezeWritesRequest(BaseModel):
    freeze: bool = True
    reason: str | None = None


class NotificationDestinationCreateRequest(BaseModel):
    tenant_id: str | None = None
    url: str = Field(..., min_length=1, max_length=1024)


class NotificationDestinationPatchRequest(BaseModel):
    enabled: bool


def _scope_tenant(principal: Principal, tenant_id: str | None) -> str:
    # Enforce tenant boundary for operator endpoints even when query params are provided.
    if tenant_id is None or tenant_id == principal.tenant_id:
        return principal.tenant_id
    raise HTTPException(status_code=403, detail={"code": "AUTHZ_DENIED", "message": "Cross-tenant access denied"})


def _incident_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "category": row.category,
        "rule_id": row.rule_id,
        "severity": row.severity,
        "status": row.status,
        "title": row.title,
        "summary": row.summary,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "acknowledged_by": row.acknowledged_by,
        "assigned_to": row.assigned_to,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolved_by": row.resolved_by,
        "details_json": row.details_json,
    }


def _action_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "action_type": row.action_type,
        "status": row.status,
        "request_json": row.request_json,
        "result_json": row.result_json,
        "error_code": row.error_code,
        "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _notification_job_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "incident_id": row.incident_id,
        "alert_event_id": row.alert_event_id,
        "destination": row.destination,
        "dedupe_key": row.dedupe_key,
        "dedupe_window_start": row.dedupe_window_start.isoformat() if row.dedupe_window_start else None,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "next_attempt_at": row.next_attempt_at.isoformat() if row.next_attempt_at else None,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _notification_destination_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "destination_url": row.destination_url,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _enforce_ops_admin(*, session: AsyncSession, principal: Principal) -> None:
    # Reuse entitlement gates so operator workflows remain plan-aware.
    await require_feature(session=session, tenant_id=principal.tenant_id, feature_key=FEATURE_OPS_ADMIN)


@router.get("/alerts/rules", response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]])
async def get_alert_rules(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # Return tenant-scoped alert rule registry for operator tuning.
    await _enforce_ops_admin(session=db, principal=principal)
    rows = await list_alert_rules(session=db, tenant_id=principal.tenant_id)
    payload = {
        "items": [
            {
                "rule_id": row.rule_id,
                "name": row.name,
                "severity": row.severity,
                "enabled": row.enabled,
                "source": row.source,
                "window": row.window,
                "expression_json": row.expression_json,
                "thresholds_json": row.thresholds_json,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]
    }
    return success_response(request=request, data=payload)


@router.patch("/alerts/rules/{rule_id}", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def patch_rule(
    rule_id: str,
    payload: AlertRulePatchRequest,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Allow bounded rule updates without replacing full definitions.
    await _enforce_ops_admin(session=db, principal=principal)
    row = await patch_alert_rule(
        session=db,
        tenant_id=principal.tenant_id,
        rule_id=rule_id,
        enabled=payload.enabled,
        severity=payload.severity,
        window=payload.window,
        thresholds_json=payload.thresholds_json,
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Alert rule not found"})
    return success_response(
        request=request,
        data={
            "rule_id": row.rule_id,
            "name": row.name,
            "severity": row.severity,
            "enabled": row.enabled,
            "source": row.source,
            "window": row.window,
            "thresholds_json": row.thresholds_json,
        },
    )


@router.post("/alerts/evaluate", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def evaluate_rules(
    request: Request,
    window: Literal["5m", "1h"] = Query(default="5m"),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Evaluate alerts on demand for deterministic triage and test scenarios.
    await _enforce_ops_admin(session=db, principal=principal)
    triggered = await evaluate_alert_rules(
        session=db,
        tenant_id=principal.tenant_id,
        window=window,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        request_id=request.headers.get("X-Request-Id"),
    )
    return success_response(request=request, data={"window": window, "triggered_alerts": triggered})


@router.get("/incidents", response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]])
async def get_incidents(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    tenant_id: str | None = Query(default=None),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # List incidents scoped to the requesting tenant with optional status filtering.
    await _enforce_ops_admin(session=db, principal=principal)
    scoped_tenant = _scope_tenant(principal, tenant_id)
    rows = await list_incidents(session=db, tenant_id=scoped_tenant, status_filter=status_filter)
    return success_response(request=request, data={"items": [_incident_payload(row) for row in rows]})


@router.post("/incidents/{incident_id}/ack", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def ack_incident(
    incident_id: str,
    request: Request,
    payload: IncidentAckRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Capture acknowledgement transitions for responder ownership and auditability.
    await _enforce_ops_admin(session=db, principal=principal)
    row = await acknowledge_incident(
        session=db,
        tenant_id=principal.tenant_id,
        incident_id=incident_id,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        note=payload.note,
        request_id=request.headers.get("X-Request-Id"),
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Incident not found"})
    return success_response(request=request, data=_incident_payload(row))


@router.post("/incidents/{incident_id}/assign", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def assign_incident_handler(
    incident_id: str,
    request: Request,
    payload: IncidentAssignRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Persist explicit incident ownership to simplify handoffs and escalation.
    await _enforce_ops_admin(session=db, principal=principal)
    row = await assign_incident(
        session=db,
        tenant_id=principal.tenant_id,
        incident_id=incident_id,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        assignee=payload.assignee,
        note=payload.note,
        request_id=request.headers.get("X-Request-Id"),
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Incident not found"})
    return success_response(request=request, data=_incident_payload(row))


@router.post("/incidents/{incident_id}/resolve", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def resolve_incident_handler(
    incident_id: str,
    request: Request,
    payload: IncidentResolveRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Resolve incidents with optional notes for postmortem readiness.
    await _enforce_ops_admin(session=db, principal=principal)
    row = await resolve_incident(
        session=db,
        tenant_id=principal.tenant_id,
        incident_id=incident_id,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        note=payload.note,
        request_id=request.headers.get("X-Request-Id"),
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Incident not found"})
    return success_response(request=request, data=_incident_payload(row))


@router.get("/notifications/jobs", response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]])
async def get_notification_jobs(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # Expose tenant-scoped notification queue state for delivery triage.
    await _enforce_ops_admin(session=db, principal=principal)
    rows = await list_notification_jobs(
        session=db,
        tenant_id=principal.tenant_id,
        status_filter=status_filter,
        limit=limit,
    )
    return success_response(request=request, data={"items": [_notification_job_payload(row) for row in rows]})


@router.get("/notifications/jobs/{job_id}", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def get_notification_job_by_id(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Return one notification job to inspect retry state and last error details.
    await _enforce_ops_admin(session=db, principal=principal)
    row = await get_notification_job(session=db, tenant_id=principal.tenant_id, job_id=job_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Notification job not found"})
    return success_response(request=request, data=_notification_job_payload(row))


@router.post("/notifications/jobs/{job_id}/retry", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def retry_notification_job(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Force a due-at-now retry while preserving dedupe and immutable attempt history.
    await _enforce_ops_admin(session=db, principal=principal)
    row = await retry_notification_job_now(session=db, tenant_id=principal.tenant_id, job_id=job_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Notification job not found"})
    return success_response(request=request, data=_notification_job_payload(row))


@router.get("/notifications/destinations", response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]])
async def get_notification_destinations(
    request: Request,
    tenant_id: str | None = Query(default=None),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # Keep destination listing tenant-scoped and explicit so routing config is operator-auditable.
    await _enforce_ops_admin(session=db, principal=principal)
    scoped_tenant = _scope_tenant(principal, tenant_id)
    rows = await list_notification_destinations(session=db, tenant_id=scoped_tenant)
    return success_response(request=request, data={"items": [_notification_destination_payload(row) for row in rows]})


@router.post("/notifications/destinations", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def create_notification_destination_handler(
    payload: NotificationDestinationCreateRequest,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Route creation through tenant scope checks to prevent cross-tenant routing injection.
    await _enforce_ops_admin(session=db, principal=principal)
    scoped_tenant = _scope_tenant(principal, payload.tenant_id)
    try:
        row = await create_notification_destination(
            session=db,
            tenant_id=scoped_tenant,
            destination_url=payload.url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_INPUT", "message": str(exc)}) from exc
    return success_response(request=request, data=_notification_destination_payload(row))


@router.patch("/notifications/destinations/{destination_id}", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def patch_notification_destination_handler(
    destination_id: str,
    payload: NotificationDestinationPatchRequest,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Toggle destination state without deleting row history so operators can re-enable quickly.
    await _enforce_ops_admin(session=db, principal=principal)
    row = await patch_notification_destination(
        session=db,
        tenant_id=principal.tenant_id,
        destination_id=destination_id,
        enabled=payload.enabled,
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Notification destination not found"})
    return success_response(request=request, data=_notification_destination_payload(row))


@router.delete("/notifications/destinations/{destination_id}", response_model=SuccessEnvelope[dict[str, bool]] | dict[str, bool])
async def delete_notification_destination_handler(
    destination_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    # Delete tenant-owned destinations only; missing rows return 404 without cross-tenant leakage.
    await _enforce_ops_admin(session=db, principal=principal)
    deleted = await delete_notification_destination(
        session=db,
        tenant_id=principal.tenant_id,
        destination_id=destination_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Notification destination not found"})
    return success_response(request=request, data={"deleted": True})


@router.get("/incidents/{incident_id}/timeline", response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]])
async def get_incident_timeline(
    incident_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # Return incident timeline rows in chronological order for operator triage.
    await _enforce_ops_admin(session=db, principal=principal)
    rows = await list_incident_timeline(session=db, tenant_id=principal.tenant_id, incident_id=incident_id)
    if not rows:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Incident not found"})
    payload = {
        "items": [
            {
                "id": row.id,
                "incident_id": row.incident_id,
                "event_type": row.event_type,
                "actor_id": row.actor_id,
                "note": row.note,
                "metadata_json": row.metadata_json,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }
    return success_response(request=request, data=payload)


def _require_idempotency_key(value: str | None) -> str:
    # Require idempotency keys for operator actions to guarantee retry-safe operations.
    if value and value.strip():
        return value.strip()
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Idempotency-Key header is required"},
    )


async def _dispatch_operator_action(
    *,
    request: Request,
    db: AsyncSession,
    principal: Principal,
    action_type: str,
    params: dict[str, Any],
    idempotency_key: str | None,
) -> Any:
    # Route all operator action endpoints through one idempotent execution path.
    idem_key = _require_idempotency_key(idempotency_key)
    request_hash = compute_request_hash({"action_type": action_type, "params": params})
    idem_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id or "unknown",
        request_hash=request_hash,
        key_override=idem_key,
    )
    if replay is not None:
        return build_replay_response(replay)  # type: ignore[return-value]

    row = await apply_operator_action(
        session=db,
        tenant_id=principal.tenant_id,
        action_type=action_type,
        idempotency_key=idem_key,
        requested_by=principal.api_key_id or "unknown",
        actor_role=principal.role,
        request_id=request.headers.get("X-Request-Id"),
        params=params,
    )
    payload = success_response(request=request, data=_action_payload(row))
    await store_idempotency_response(
        db=db,
        context=idem_ctx,
        response_status=200,
        response_body=jsonable_encoder(payload),
    )
    return payload


@router.post("/ops/actions/freeze-writes", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def freeze_writes_action(
    request: Request,
    payload: FreezeWritesRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Expose write-freeze controls in the unified operator action workflow.
    await _enforce_ops_admin(session=db, principal=principal)
    return await _dispatch_operator_action(
        request=request,
        db=db,
        principal=principal,
        action_type="freeze_writes",
        params=payload.model_dump(),
        idempotency_key=_idempotency_key,
    )


@router.post("/ops/actions/enable-shed", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def enable_shed_action(
    request: Request,
    route_class: str = Query(default="run"),
    tenant_id: str | None = Query(default=None),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Allow operators to force shed decisions for specific route classes during incidents.
    await _enforce_ops_admin(session=db, principal=principal)
    scoped_tenant = _scope_tenant(principal, tenant_id)
    return await _dispatch_operator_action(
        request=request,
        db=db,
        principal=principal,
        action_type="enable_shed",
        params={"tenant_id": scoped_tenant, "route_class": route_class},
        idempotency_key=_idempotency_key,
    )


@router.post("/ops/actions/disable-tts", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def disable_tts_action(
    request: Request,
    tenant_id: str | None = Query(default=None),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Allow operators to disable TTS quickly when latency/cost incidents occur.
    await _enforce_ops_admin(session=db, principal=principal)
    scoped_tenant = _scope_tenant(principal, tenant_id)
    return await _dispatch_operator_action(
        request=request,
        db=db,
        principal=principal,
        action_type="disable_tts",
        params={"tenant_id": scoped_tenant},
        idempotency_key=_idempotency_key,
    )


@router.post("/ops/actions/reset-breaker", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def reset_breaker_action(
    request: Request,
    integration: str = Query(..., min_length=1),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Allow controlled breaker resets to validate dependency recovery.
    await _enforce_ops_admin(session=db, principal=principal)
    return await _dispatch_operator_action(
        request=request,
        db=db,
        principal=principal,
        action_type="reset_breaker",
        params={"integration": integration},
        idempotency_key=_idempotency_key,
    )
