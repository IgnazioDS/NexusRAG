from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, idempotency_key_header, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.domain.models import (
    AutoscalingAction,
    AutoscalingProfile,
    SlaIncident,
    SlaMeasurement,
    SlaPolicy,
    TenantSlaAssignment,
)
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)
from nexusrag.services.sla.autoscaling import (
    AutoscalingCooldownError,
    AutoscalingExecutorUnavailableError,
    AutoscalingSignal,
    apply_autoscaling,
    evaluate_autoscaling,
)
from nexusrag.services.sla.policy import (
    SlaPolicyValidationError,
    parse_policy_config,
)
from nexusrag.services.sla.signals import window_seconds_for_label


router = APIRouter(prefix="/admin/sla", tags=["sla"], responses=DEFAULT_ERROR_RESPONSES)

_VALID_ROUTE_CLASSES = {"run", "read", "mutation", "ingest", "ops", "admin"}


def _utc_now() -> datetime:
    # Use UTC for assignment effective windows and incident resolution timestamps.
    return datetime.now(timezone.utc)


def _scope_tenant(principal: Principal, tenant_id: str | None) -> str:
    # Enforce tenant boundaries for tenant-scoped admin paths and query params.
    effective_tenant = tenant_id or principal.tenant_id
    if effective_tenant != principal.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "AUTH_FORBIDDEN", "message": "Cross-tenant SLA access denied"},
        )
    return effective_tenant


def _policy_payload(policy: SlaPolicy) -> dict[str, Any]:
    # Normalize policy rows to JSON-safe payloads.
    return {
        "id": policy.id,
        "tenant_id": policy.tenant_id,
        "name": policy.name,
        "tier": policy.tier,
        "enabled": bool(policy.enabled),
        "config_json": policy.config_json,
        "version": int(policy.version),
        "created_by": policy.created_by,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def _assignment_payload(assignment: TenantSlaAssignment) -> dict[str, Any]:
    # Serialize assignment timestamps for API clients.
    return {
        "id": assignment.id,
        "tenant_id": assignment.tenant_id,
        "policy_id": assignment.policy_id,
        "effective_from": assignment.effective_from.isoformat(),
        "effective_to": assignment.effective_to.isoformat() if assignment.effective_to else None,
        "override_json": assignment.override_json,
        "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
        "updated_at": assignment.updated_at.isoformat() if assignment.updated_at else None,
    }


def _measurement_payload(row: SlaMeasurement) -> dict[str, Any]:
    # Keep measurement payloads compact and deterministic for trend consumers.
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "route_class": row.route_class,
        "window_start": row.window_start.isoformat(),
        "window_end": row.window_end.isoformat(),
        "request_count": int(row.request_count),
        "error_count": int(row.error_count),
        "p50_ms": float(row.p50_ms) if row.p50_ms is not None else None,
        "p95_ms": float(row.p95_ms) if row.p95_ms is not None else None,
        "p99_ms": float(row.p99_ms) if row.p99_ms is not None else None,
        "availability_pct": float(row.availability_pct) if row.availability_pct is not None else None,
        "saturation_pct": float(row.saturation_pct) if row.saturation_pct is not None else None,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
    }


def _incident_payload(row: SlaIncident) -> dict[str, Any]:
    # Serialize incident lifecycle fields for operator dashboards.
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "policy_id": row.policy_id,
        "route_class": row.route_class,
        "breach_type": row.breach_type,
        "severity": row.severity,
        "status": row.status,
        "first_breach_at": row.first_breach_at.isoformat(),
        "last_breach_at": row.last_breach_at.isoformat(),
        "details_json": row.details_json,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def _profile_payload(row: AutoscalingProfile) -> dict[str, Any]:
    # Keep profile payloads stable for dry-run/apply workflows.
    return {
        "id": row.id,
        "name": row.name,
        "scope": row.scope,
        "tenant_id": row.tenant_id,
        "route_class": row.route_class,
        "min_replicas": row.min_replicas,
        "max_replicas": row.max_replicas,
        "target_p95_ms": row.target_p95_ms,
        "target_queue_depth": row.target_queue_depth,
        "cooldown_seconds": row.cooldown_seconds,
        "step_up": row.step_up,
        "step_down": row.step_down,
        "enabled": bool(row.enabled),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _action_payload(row: AutoscalingAction) -> dict[str, Any]:
    # Serialize persisted autoscaling actions for auditability.
    return {
        "id": row.id,
        "profile_id": row.profile_id,
        "tenant_id": row.tenant_id,
        "route_class": row.route_class,
        "action": row.action,
        "from_replicas": row.from_replicas,
        "to_replicas": row.to_replicas,
        "reason": row.reason,
        "signal_json": row.signal_json,
        "executed": bool(row.executed),
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _validate_route_class(route_class: str) -> str:
    # Enforce canonical route_class values for policy/profile consistency.
    value = str(route_class)
    if value not in _VALID_ROUTE_CLASSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SLA_POLICY_INVALID", "message": "route_class is invalid"},
        )
    return value


def _validate_profile_bounds(payload: dict[str, Any]) -> None:
    # Prevent invalid autoscaling profile bounds from being persisted.
    min_replicas = int(payload["min_replicas"])
    max_replicas = int(payload["max_replicas"])
    if min_replicas < 1 or max_replicas < 1 or min_replicas > max_replicas:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SLA_AUTOSCALING_PROFILE_INVALID", "message": "Invalid replica bounds"},
        )
    if int(payload["cooldown_seconds"]) < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SLA_AUTOSCALING_PROFILE_INVALID", "message": "cooldown_seconds must be >= 0"},
        )


def _merge_json(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    # Merge override payloads recursively for assignment validation.
    merged = dict(base)
    if not override:
        return merged
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_json(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


class SlaPolicyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    tier: Literal["standard", "pro", "enterprise", "custom"]
    enabled: bool = True
    config_json: dict[str, Any]
    version: int = Field(default=1, ge=1)

    # Reject unknown fields so policy writes remain explicit.
    model_config = {"extra": "forbid"}


class SlaPolicyPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    tier: Literal["standard", "pro", "enterprise", "custom"] | None = None
    enabled: bool | None = None
    config_json: dict[str, Any] | None = None

    # Reject unknown fields so policy updates remain explicit.
    model_config = {"extra": "forbid"}


class SlaAssignmentPatchRequest(BaseModel):
    policy_id: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    override_json: dict[str, Any] | None = None

    # Reject unknown fields to keep assignment state deterministic.
    model_config = {"extra": "forbid"}


class AutoscalingProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scope: Literal["global", "tenant", "route_class"]
    tenant_id: str | None = None
    route_class: str | None = None
    min_replicas: int = Field(ge=1)
    max_replicas: int = Field(ge=1)
    target_p95_ms: int = Field(ge=1)
    target_queue_depth: int = Field(ge=0)
    cooldown_seconds: int = Field(ge=0)
    step_up: int = Field(ge=1)
    step_down: int = Field(ge=1)
    enabled: bool = True

    # Reject unknown fields so autoscaling profile writes are explicit.
    model_config = {"extra": "forbid"}


class AutoscalingProfilePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    tenant_id: str | None = None
    route_class: str | None = None
    min_replicas: int | None = Field(default=None, ge=1)
    max_replicas: int | None = Field(default=None, ge=1)
    target_p95_ms: int | None = Field(default=None, ge=1)
    target_queue_depth: int | None = Field(default=None, ge=0)
    cooldown_seconds: int | None = Field(default=None, ge=0)
    step_up: int | None = Field(default=None, ge=1)
    step_down: int | None = Field(default=None, ge=1)
    enabled: bool | None = None

    # Reject unknown fields so autoscaling profile updates are explicit.
    model_config = {"extra": "forbid"}


class AutoscalingEvaluateRequest(BaseModel):
    profile_id: str
    route_class: str
    current_replicas: int = Field(ge=1)
    p95_ms: float | None = Field(default=None, ge=0)
    queue_depth: int | None = Field(default=None, ge=0)
    signal_quality: Literal["ok", "degraded"] = "ok"

    # Reject unknown fields so recommendation input remains deterministic.
    model_config = {"extra": "forbid"}


class AutoscalingApplyRequest(AutoscalingEvaluateRequest):
    pass


@router.get("/policies", response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]])
async def list_policies(
    request: Request,
    include_global: bool = Query(default=True),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # List tenant and optional global policies ordered by newest updates first.
    query = select(SlaPolicy).where(SlaPolicy.tenant_id == principal.tenant_id)
    if include_global:
        query = select(SlaPolicy).where(
            or_(SlaPolicy.tenant_id == principal.tenant_id, SlaPolicy.tenant_id.is_(None))
        )
    rows = (
        await db.execute(query.order_by(SlaPolicy.updated_at.desc(), SlaPolicy.created_at.desc()))
    ).scalars().all()
    return success_response(request=request, data={"items": [_policy_payload(row) for row in rows]})


@router.post(
    "/policies",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def create_policy(
    request: Request,
    payload: SlaPolicyCreateRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Create tenant-scoped SLA policies after strict schema validation.
    try:
        parse_policy_config(payload.config_json)
    except SlaPolicyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SLA_POLICY_INVALID", "message": str(exc)},
        ) from exc

    request_hash = compute_request_hash(payload.model_dump())
    idem_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    row = SlaPolicy(
        id=uuid4().hex,
        tenant_id=principal.tenant_id,
        name=payload.name,
        tier=payload.tier,
        enabled=payload.enabled,
        config_json=payload.config_json,
        version=payload.version,
        created_by=principal.api_key_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="sla.policy.created",
        outcome="success",
        resource_type="sla_policy",
        resource_id=row.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"name": row.name, "tier": row.tier, "version": row.version},
        commit=True,
        best_effort=True,
    )
    body = success_response(request=request, data=_policy_payload(row))
    await store_idempotency_response(
        db=db,
        context=idem_ctx,
        response_status=status.HTTP_201_CREATED,
        response_body=jsonable_encoder(body),
    )
    return body


@router.patch("/policies/{policy_id}", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def patch_policy(
    policy_id: str,
    request: Request,
    payload: SlaPolicyPatchRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Patch policy fields while preserving tenant isolation boundaries.
    request_hash = compute_request_hash({"policy_id": policy_id, **payload.model_dump(exclude_none=True)})
    idem_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    row = await db.get(SlaPolicy, policy_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "SLA policy not found"})
    updates = payload.model_dump(exclude_none=True)
    if "config_json" in updates:
        try:
            parse_policy_config(updates["config_json"])
        except SlaPolicyValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "SLA_POLICY_INVALID", "message": str(exc)},
            ) from exc
    for key, value in updates.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="sla.policy.updated",
        outcome="success",
        resource_type="sla_policy",
        resource_id=row.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"updated_fields": sorted(updates.keys())},
        commit=True,
        best_effort=True,
    )
    body = success_response(request=request, data=_policy_payload(row))
    await store_idempotency_response(
        db=db,
        context=idem_ctx,
        response_status=status.HTTP_200_OK,
        response_body=jsonable_encoder(body),
    )
    return body


@router.post("/policies/{policy_id}/enable", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def enable_policy(
    policy_id: str,
    request: Request,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Enable tenant policy revisions with an auditable mutation path.
    row = await db.get(SlaPolicy, policy_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "SLA policy not found"})
    row.enabled = True
    await db.commit()
    await db.refresh(row)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="sla.policy.enabled",
        outcome="success",
        resource_type="sla_policy",
        resource_id=row.id,
        request_id=get_request_context(request)["request_id"],
        metadata={},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_policy_payload(row))


@router.post("/policies/{policy_id}/disable", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def disable_policy(
    policy_id: str,
    request: Request,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Disable tenant policy revisions with an auditable mutation path.
    row = await db.get(SlaPolicy, policy_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "SLA policy not found"})
    row.enabled = False
    await db.commit()
    await db.refresh(row)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="sla.policy.disabled",
        outcome="success",
        resource_type="sla_policy",
        resource_id=row.id,
        request_id=get_request_context(request)["request_id"],
        metadata={},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_policy_payload(row))


@router.get("/assignments/{tenant_id}", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def get_assignment(
    tenant_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Return active tenant assignment metadata for SLA policy introspection.
    scoped_tenant = _scope_tenant(principal, tenant_id)
    result = await db.execute(
        select(TenantSlaAssignment)
        .where(TenantSlaAssignment.tenant_id == scoped_tenant)
        .order_by(TenantSlaAssignment.updated_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SLA_ASSIGNMENT_NOT_FOUND", "message": "SLA assignment not found"},
        )
    return success_response(request=request, data=_assignment_payload(row))


@router.patch("/assignments/{tenant_id}", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def patch_assignment(
    tenant_id: str,
    request: Request,
    payload: SlaAssignmentPatchRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Create or update tenant assignment records with optional policy overrides.
    scoped_tenant = _scope_tenant(principal, tenant_id)
    policy = await db.get(SlaPolicy, payload.policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "SLA policy not found"})
    if policy.tenant_id not in {None, scoped_tenant}:
        raise HTTPException(status_code=403, detail={"code": "AUTH_FORBIDDEN", "message": "Policy scope mismatch"})

    if payload.override_json is not None:
        try:
            parse_policy_config(_merge_json(policy.config_json or {}, payload.override_json))
        except SlaPolicyValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "SLA_POLICY_INVALID", "message": str(exc)},
            ) from exc

    result = await db.execute(
        select(TenantSlaAssignment).where(TenantSlaAssignment.tenant_id == scoped_tenant).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = TenantSlaAssignment(
            id=uuid4().hex,
            tenant_id=scoped_tenant,
            policy_id=payload.policy_id,
            effective_from=payload.effective_from or _utc_now(),
            effective_to=payload.effective_to,
            override_json=payload.override_json,
        )
        db.add(row)
    else:
        row.policy_id = payload.policy_id
        row.effective_from = payload.effective_from or row.effective_from
        row.effective_to = payload.effective_to
        row.override_json = payload.override_json
    await db.commit()
    await db.refresh(row)
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=scoped_tenant,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="sla.assignment.updated",
        outcome="success",
        resource_type="sla_assignment",
        resource_id=row.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"policy_id": row.policy_id},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_assignment_payload(row))


@router.get("/measurements", response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]])
async def list_measurements(
    request: Request,
    tenant_id: str | None = Query(default=None),
    route_class: str | None = Query(default=None),
    window: Literal["1m", "5m"] = Query(default="1m"),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # Return latest measurements for tenant-scoped SLA troubleshooting.
    scoped_tenant = _scope_tenant(principal, tenant_id)
    seconds = window_seconds_for_label(window)
    query = select(SlaMeasurement).where(SlaMeasurement.tenant_id == scoped_tenant)
    if route_class is not None:
        query = query.where(SlaMeasurement.route_class == _validate_route_class(route_class))
    rows = (
        await db.execute(query.order_by(SlaMeasurement.window_end.desc()).limit(max(limit * 5, 25)))
    ).scalars().all()
    filtered = [
        row
        for row in rows
        if int((row.window_end - row.window_start).total_seconds()) == seconds
    ][:limit]
    return success_response(request=request, data={"items": [_measurement_payload(row) for row in filtered]})


@router.get("/incidents", response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]])
async def list_incidents(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # Return SLA incidents for tenant operators.
    query = select(SlaIncident).where(SlaIncident.tenant_id == principal.tenant_id)
    if status_filter is not None:
        query = query.where(SlaIncident.status == status_filter)
    rows = (await db.execute(query.order_by(SlaIncident.last_breach_at.desc()))).scalars().all()
    return success_response(request=request, data={"items": [_incident_payload(row) for row in rows]})


@router.post("/incidents/{incident_id}/resolve", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def resolve_incident(
    incident_id: str,
    request: Request,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Resolve incidents with immutable timestamps for postmortem workflows.
    row = await db.get(SlaIncident, incident_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "SLA incident not found"})
    row.status = "resolved"
    row.resolved_at = _utc_now()
    await db.commit()
    await db.refresh(row)
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="sla.incident.resolved",
        outcome="success",
        resource_type="sla_incident",
        resource_id=row.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_incident_payload(row))


@router.get(
    "/autoscaling/profiles",
    response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]],
)
async def list_profiles(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # List global and tenant profiles visible to the current tenant admin.
    rows = (
        await db.execute(
            select(AutoscalingProfile)
            .where(or_(AutoscalingProfile.tenant_id == principal.tenant_id, AutoscalingProfile.tenant_id.is_(None)))
            .order_by(AutoscalingProfile.updated_at.desc())
        )
    ).scalars().all()
    return success_response(request=request, data={"items": [_profile_payload(row) for row in rows]})


@router.post(
    "/autoscaling/profiles",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def create_profile(
    request: Request,
    payload: AutoscalingProfileCreateRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Create autoscaling profiles bounded to tenant scope when applicable.
    if payload.route_class is not None:
        _validate_route_class(payload.route_class)
    scoped_tenant = _scope_tenant(principal, payload.tenant_id) if payload.tenant_id else principal.tenant_id
    values = payload.model_dump()
    values["tenant_id"] = scoped_tenant
    _validate_profile_bounds(values)
    row = AutoscalingProfile(id=uuid4().hex, **values)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="sla.autoscaling.profile.created",
        outcome="success",
        resource_type="autoscaling_profile",
        resource_id=row.id,
        request_id=get_request_context(request)["request_id"],
        metadata={"scope": row.scope, "route_class": row.route_class},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_profile_payload(row))


@router.patch("/autoscaling/profiles/{profile_id}", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def patch_profile(
    profile_id: str,
    request: Request,
    payload: AutoscalingProfilePatchRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Update autoscaling profiles with strict bounds checks.
    row = await db.get(AutoscalingProfile, profile_id)
    if row is None or row.tenant_id not in {principal.tenant_id, None}:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Autoscaling profile not found"})
    updates = payload.model_dump(exclude_none=True)
    if "route_class" in updates:
        updates["route_class"] = _validate_route_class(updates["route_class"])
    if "tenant_id" in updates and updates["tenant_id"] is not None:
        updates["tenant_id"] = _scope_tenant(principal, updates["tenant_id"])
    merged = _profile_payload(row)
    merged.update(updates)
    _validate_profile_bounds(merged)
    for key, value in updates.items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return success_response(request=request, data=_profile_payload(row))


@router.post("/autoscaling/evaluate", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def evaluate_profile(
    request: Request,
    payload: AutoscalingEvaluateRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Run dry-run autoscaling evaluation and persist recommendation traces.
    _validate_route_class(payload.route_class)
    profile = await db.get(AutoscalingProfile, payload.profile_id)
    if profile is None or profile.tenant_id not in {principal.tenant_id, None}:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Autoscaling profile not found"})
    recommendation = await evaluate_autoscaling(
        session=db,
        profile=profile,
        tenant_id=principal.tenant_id,
        signal=AutoscalingSignal(
            route_class=payload.route_class,
            current_replicas=payload.current_replicas,
            p95_ms=payload.p95_ms,
            queue_depth=payload.queue_depth,
            signal_quality=payload.signal_quality,
        ),
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        request_id=get_request_context(request)["request_id"],
    )
    return success_response(
        request=request,
        data={
            "action": recommendation.action,
            "from_replicas": recommendation.from_replicas,
            "to_replicas": recommendation.to_replicas,
            "reason": recommendation.reason,
            "cooldown_active": recommendation.cooldown_active,
            "signal_json": recommendation.signal_json,
        },
    )


@router.post("/autoscaling/apply", response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any])
async def apply_profile(
    request: Request,
    payload: AutoscalingApplyRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Apply autoscaling recommendations via configured executor adapters.
    _validate_route_class(payload.route_class)
    profile = await db.get(AutoscalingProfile, payload.profile_id)
    if profile is None or profile.tenant_id not in {principal.tenant_id, None}:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Autoscaling profile not found"})
    try:
        recommendation = await apply_autoscaling(
            session=db,
            profile=profile,
            tenant_id=principal.tenant_id,
            signal=AutoscalingSignal(
                route_class=payload.route_class,
                current_replicas=payload.current_replicas,
                p95_ms=payload.p95_ms,
                queue_depth=payload.queue_depth,
                signal_quality=payload.signal_quality,
            ),
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            request_id=get_request_context(request)["request_id"],
        )
    except AutoscalingCooldownError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SLA_AUTOSCALING_COOLDOWN_ACTIVE", "message": str(exc)},
        ) from exc
    except AutoscalingExecutorUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "SLA_AUTOSCALING_EXECUTOR_UNAVAILABLE", "message": str(exc)},
        ) from exc
    return success_response(
        request=request,
        data={
            "action": recommendation.action,
            "from_replicas": recommendation.from_replicas,
            "to_replicas": recommendation.to_replicas,
            "reason": recommendation.reason,
            "cooldown_active": recommendation.cooldown_active,
            "signal_json": recommendation.signal_json,
        },
    )


@router.get(
    "/autoscaling/actions",
    response_model=SuccessEnvelope[dict[str, list[dict[str, Any]]]] | dict[str, list[dict[str, Any]]],
)
async def list_actions(
    request: Request,
    profile_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    # Return tenant-visible autoscaling action history for audits.
    query = select(AutoscalingAction).where(
        or_(AutoscalingAction.tenant_id == principal.tenant_id, AutoscalingAction.tenant_id.is_(None))
    )
    if profile_id is not None:
        query = query.where(AutoscalingAction.profile_id == profile_id)
    rows = (await db.execute(query.order_by(AutoscalingAction.created_at.desc()).limit(limit))).scalars().all()
    return success_response(request=request, data={"items": [_action_payload(row) for row in rows]})
