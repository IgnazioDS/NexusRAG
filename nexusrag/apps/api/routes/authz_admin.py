from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import (
    Principal,
    get_db,
    idempotency_key_header,
    reject_tenant_id_in_body,
    require_role,
)
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import AuthorizationPolicy, DocumentPermission
from nexusrag.persistence.repos import authz as authz_repo
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.authz.abac import evaluate_policy_set, validate_policy_condition
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)


router = APIRouter(prefix="/admin/authz", tags=["authz"], responses=DEFAULT_ERROR_RESPONSES)

_ALLOWED_RESOURCE_TYPES = {"document", "corpus", "run", "admin", "ops", "audit", "*"}
_ALLOWED_ACTIONS = {"read", "write", "delete", "reindex", "run", "manage", "*"}


class PolicyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    effect: Literal["allow", "deny"]
    resource_type: str
    action: str
    condition_json: dict[str, Any] | None = None
    priority: int = Field(default=100)
    enabled: bool = True

    # Reject unknown fields so tenants cannot spoof policy properties.
    model_config = {"extra": "forbid"}


class PolicyPatchRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    effect: Literal["allow", "deny"] | None = None
    resource_type: str | None = None
    action: str | None = None
    condition_json: dict[str, Any] | None = None
    priority: int | None = None
    enabled: bool | None = None

    # Reject unknown fields so tenants cannot spoof policy properties.
    model_config = {"extra": "forbid"}


class PolicyResponse(BaseModel):
    id: str
    tenant_id: str | None
    name: str
    version: int
    effect: str
    resource_type: str
    action: str
    condition_json: dict[str, Any] | None
    priority: int
    enabled: bool
    created_by: str | None
    created_at: str | None
    updated_at: str | None


class PolicyListResponse(BaseModel):
    items: list[PolicyResponse]


class PolicySimulationRequest(BaseModel):
    resource_type: str
    action: str
    principal: dict[str, Any] | None = None
    resource: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    context: dict[str, Any] | None = None

    # Reject unknown fields so simulations remain deterministic.
    model_config = {"extra": "forbid"}


class PolicySimulationResponse(BaseModel):
    allowed: bool
    reason: str
    matched_policy_id: str | None
    matched_policies: list[str]
    trace: list[dict[str, Any]]


class DocumentPermissionRequest(BaseModel):
    principal_type: Literal["user", "api_key", "group", "role"]
    principal_id: str = Field(min_length=1, max_length=128)
    permission: Literal["read", "write", "delete", "reindex", "owner"]
    expires_at: datetime | None = None

    # Reject unknown fields to keep permission rows explicit.
    model_config = {"extra": "forbid"}


class DocumentPermissionResponse(BaseModel):
    id: str
    tenant_id: str
    document_id: str
    principal_type: str
    principal_id: str
    permission: str
    granted_by: str | None
    expires_at: str | None
    created_at: str | None


class DocumentPermissionList(BaseModel):
    items: list[DocumentPermissionResponse]


class DocumentPermissionBulkRequest(BaseModel):
    permissions: list[DocumentPermissionRequest]

    # Reject unknown fields to keep bulk writes predictable.
    model_config = {"extra": "forbid"}


class DocumentPermissionBulkResponse(BaseModel):
    items: list[DocumentPermissionResponse]


def _utc_now() -> datetime:
    # Normalize authz timestamps to UTC for deterministic auditing.
    return datetime.now(timezone.utc)


def _policy_payload(policy: AuthorizationPolicy) -> PolicyResponse:
    # Serialize policy rows into API responses.
    return PolicyResponse(
        id=policy.id,
        tenant_id=policy.tenant_id,
        name=policy.name,
        version=policy.version,
        effect=policy.effect,
        resource_type=policy.resource_type,
        action=policy.action,
        condition_json=policy.condition_json,
        priority=policy.priority,
        enabled=policy.enabled,
        created_by=policy.created_by,
        created_at=policy.created_at.isoformat() if policy.created_at else None,
        updated_at=policy.updated_at.isoformat() if policy.updated_at else None,
    )


def _permission_payload(permission: DocumentPermission) -> DocumentPermissionResponse:
    # Serialize document permission rows into API responses.
    return DocumentPermissionResponse(
        id=permission.id,
        tenant_id=permission.tenant_id,
        document_id=permission.document_id,
        principal_type=permission.principal_type,
        principal_id=permission.principal_id,
        permission=permission.permission,
        granted_by=permission.granted_by,
        expires_at=permission.expires_at.isoformat() if permission.expires_at else None,
        created_at=permission.created_at.isoformat() if permission.created_at else None,
    )


def _policy_scope_error(code: str, message: str) -> HTTPException:
    # Standardize policy scope validation errors.
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": code, "message": message},
    )


def _simulation_error(message: str) -> HTTPException:
    # Report simulation input issues with a stable error code.
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "AUTHZ_SIMULATION_INVALID", "message": message},
    )


def _ensure_allowed_scope(resource_type: str, action: str) -> None:
    # Validate policy scopes against supported resource/action values.
    if resource_type not in _ALLOWED_RESOURCE_TYPES:
        raise _policy_scope_error("AUTHZ_POLICY_INVALID", "Unsupported resource_type")
    if action not in _ALLOWED_ACTIONS:
        raise _policy_scope_error("AUTHZ_POLICY_INVALID", "Unsupported action")
    settings = get_settings()
    if resource_type == "*" and action == "*" and not settings.authz_allow_wildcards:
        raise _policy_scope_error("AUTHZ_POLICY_INVALID", "Wildcard policies require explicit enablement")


def _ensure_allowed_simulation_scope(resource_type: str, action: str) -> None:
    # Validate simulation scopes without persisting them.
    if resource_type not in _ALLOWED_RESOURCE_TYPES:
        raise _simulation_error("Unsupported resource_type")
    if action not in _ALLOWED_ACTIONS:
        raise _simulation_error("Unsupported action")


def _merge_context(base: dict[str, Any], updates: dict[str, Any] | None) -> dict[str, Any]:
    # Merge nested context blocks without mutating the caller's dict.
    if not updates:
        return base
    merged = dict(base)
    merged.update(updates)
    return merged


def _build_simulation_context(
    *,
    principal: Principal,
    payload: PolicySimulationRequest,
) -> dict[str, Any]:
    # Compose simulation context with explicit tenant boundaries.
    context: dict[str, Any] = dict(payload.context or {})
    principal_ctx = _merge_context({"tenant_id": principal.tenant_id}, payload.principal)
    resource_ctx = _merge_context({}, payload.resource)
    request_ctx = _merge_context({}, payload.request)

    if "tenant_id" in principal_ctx and principal_ctx["tenant_id"] != principal.tenant_id:
        raise _simulation_error("Simulation tenant_id must match the caller")
    if "tenant_id" in resource_ctx and resource_ctx["tenant_id"] != principal.tenant_id:
        raise _simulation_error("Resource tenant_id must match the caller")

    context["principal"] = principal_ctx
    context["resource"] = resource_ctx
    context["request"] = request_ctx
    if "time" not in context.get("request", {}):
        context["request"]["time"] = _utc_now().isoformat()
    return context


def _clone_policy(policy: AuthorizationPolicy, *, enabled_override: bool | None = None) -> AuthorizationPolicy:
    # Create a detached policy copy for simulation without mutating the ORM state.
    return AuthorizationPolicy(
        id=policy.id,
        tenant_id=policy.tenant_id,
        name=policy.name,
        version=policy.version,
        effect=policy.effect,
        resource_type=policy.resource_type,
        action=policy.action,
        condition_json=policy.condition_json,
        priority=policy.priority,
        enabled=policy.enabled if enabled_override is None else enabled_override,
        created_by=policy.created_by,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


async def _ensure_document_visible(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: str,
) -> None:
    # Avoid leaking document existence across tenants.
    doc = await documents_repo.get_document(session, tenant_id, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Document not found"},
        )


async def _find_permission(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: str,
    payload: DocumentPermissionRequest,
) -> DocumentPermission | None:
    # Check for an existing permission to keep grants idempotent.
    result = await session.execute(
        select(DocumentPermission).where(
            DocumentPermission.tenant_id == tenant_id,
            DocumentPermission.document_id == document_id,
            DocumentPermission.principal_type == payload.principal_type,
            DocumentPermission.principal_id == payload.principal_id,
            DocumentPermission.permission == payload.permission,
        )
    )
    return result.scalar_one_or_none()


async def _grant_permission(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: str,
    payload: DocumentPermissionRequest,
    granted_by: str,
) -> tuple[DocumentPermission, bool]:
    # Create document permissions with explicit idempotency handling.
    existing = await _find_permission(
        session=session,
        tenant_id=tenant_id,
        document_id=document_id,
        payload=payload,
    )
    if existing is not None:
        return existing, False
    permission = DocumentPermission(
        id=uuid4().hex,
        tenant_id=tenant_id,
        document_id=document_id,
        principal_type=payload.principal_type,
        principal_id=payload.principal_id,
        permission=payload.permission,
        granted_by=granted_by,
        expires_at=payload.expires_at,
    )
    session.add(permission)
    return permission, True


@router.get("/policies", response_model=SuccessEnvelope[PolicyListResponse] | PolicyListResponse)
async def list_policies(
    request: Request,
    include_global: bool = True,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyListResponse:
    # Return tenant-scoped policy inventory for admin management.
    policies = await authz_repo.list_policies(
        db,
        tenant_id=principal.tenant_id,
        include_global=include_global,
        include_disabled=True,
    )
    payload = PolicyListResponse(items=[_policy_payload(policy) for policy in policies])
    return success_response(request=request, data=payload)


@router.post(
    "/policies",
    response_model=SuccessEnvelope[PolicyResponse] | PolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy(
    request: Request,
    payload: PolicyCreateRequest,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    # Create ABAC policies with validation and audit tracking.
    request_hash = compute_request_hash(payload.model_dump())
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    _ensure_allowed_scope(payload.resource_type, payload.action)
    validate_policy_condition(payload.condition_json)

    policy = AuthorizationPolicy(
        id=uuid4().hex,
        tenant_id=principal.tenant_id,
        name=payload.name,
        version=1,
        effect=payload.effect,
        resource_type=payload.resource_type,
        action=payload.action,
        condition_json=payload.condition_json or {},
        priority=payload.priority,
        enabled=payload.enabled,
        created_by=principal.api_key_id,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type=principal.auth_method,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="authz.policy.created",
        outcome="success",
        resource_type="authorization_policy",
        resource_id=policy.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "resource_type": policy.resource_type,
            "action": policy.action,
            "effect": policy.effect,
        },
        commit=True,
        best_effort=True,
    )

    response_payload = _policy_payload(policy)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=status.HTTP_201_CREATED,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.patch("/policies/{policy_id}", response_model=SuccessEnvelope[PolicyResponse] | PolicyResponse)
async def patch_policy(
    policy_id: str,
    request: Request,
    payload: PolicyPatchRequest,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    # Patch policies with explicit tenant scoping and versioning.
    request_hash = compute_request_hash({"policy_id": policy_id, "payload": payload.model_dump(exclude_unset=True)})
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    policy = await authz_repo.get_policy(
        db,
        tenant_id=principal.tenant_id,
        policy_id=policy_id,
        include_global=False,
    )
    if policy is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Policy not found"})

    updates = payload.model_dump(exclude_unset=True)
    resource_type = updates.get("resource_type", policy.resource_type)
    action = updates.get("action", policy.action)
    _ensure_allowed_scope(resource_type, action)
    if "condition_json" in updates:
        validate_policy_condition(updates.get("condition_json"))
    for key, value in updates.items():
        setattr(policy, key, value)
    if updates:
        policy.version = policy.version + 1

    await db.commit()
    await db.refresh(policy)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type=principal.auth_method,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="authz.policy.updated",
        outcome="success",
        resource_type="authorization_policy",
        resource_id=policy.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"updated_fields": list(updates.keys())},
        commit=True,
        best_effort=True,
    )

    response_payload = _policy_payload(policy)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=status.HTTP_200_OK,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.post("/policies/{policy_id}/enable", response_model=SuccessEnvelope[PolicyResponse] | PolicyResponse)
async def enable_policy(
    policy_id: str,
    request: Request,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    # Enable policies without mutating other fields.
    request_hash = compute_request_hash({"policy_id": policy_id, "enabled": True})
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    policy = await authz_repo.get_policy(
        db,
        tenant_id=principal.tenant_id,
        policy_id=policy_id,
        include_global=False,
    )
    if policy is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Policy not found"})
    policy.enabled = True
    await db.commit()
    await db.refresh(policy)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type=principal.auth_method,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="authz.policy.enabled",
        outcome="success",
        resource_type="authorization_policy",
        resource_id=policy.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata=None,
        commit=True,
        best_effort=True,
    )

    response_payload = _policy_payload(policy)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=status.HTTP_200_OK,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.post("/policies/{policy_id}/disable", response_model=SuccessEnvelope[PolicyResponse] | PolicyResponse)
async def disable_policy(
    policy_id: str,
    request: Request,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    # Disable policies without deleting audit history.
    request_hash = compute_request_hash({"policy_id": policy_id, "enabled": False})
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    policy = await authz_repo.get_policy(
        db,
        tenant_id=principal.tenant_id,
        policy_id=policy_id,
        include_global=False,
    )
    if policy is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Policy not found"})
    policy.enabled = False
    await db.commit()
    await db.refresh(policy)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type=principal.auth_method,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="authz.policy.disabled",
        outcome="success",
        resource_type="authorization_policy",
        resource_id=policy.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata=None,
        commit=True,
        best_effort=True,
    )

    response_payload = _policy_payload(policy)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=status.HTTP_200_OK,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.post("/policies/{policy_id}/simulate", response_model=SuccessEnvelope[PolicySimulationResponse] | PolicySimulationResponse)
async def simulate_policy(
    policy_id: str,
    request: Request,
    payload: PolicySimulationRequest,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicySimulationResponse:
    # Provide a policy simulation endpoint with trace output for admins.
    settings = get_settings()
    if not settings.authz_simulation_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "AUTHZ_DENIED", "message": "Policy simulation is disabled"},
        )
    _ensure_allowed_simulation_scope(payload.resource_type, payload.action)
    policy = await authz_repo.get_policy(
        db,
        tenant_id=principal.tenant_id,
        policy_id=policy_id,
        include_global=True,
    )
    if policy is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Policy not found"})

    context = _build_simulation_context(principal=principal, payload=payload)
    policy_set = await authz_repo.list_policies(
        db,
        tenant_id=principal.tenant_id,
        include_global=True,
        include_disabled=False,
    )
    simulated_policy = _clone_policy(policy, enabled_override=True)
    policy_set = [p for p in policy_set if p.id != policy.id]
    policy_set.append(simulated_policy)
    policy_set.sort(key=lambda item: (-item.priority, item.id))
    decision = evaluate_policy_set(
        policies=policy_set,
        resource_type=payload.resource_type,
        action=payload.action,
        context=context,
        include_trace=True,
        default_deny=settings.authz_default_deny,
    )

    matched_policies = [trace["policy_id"] for trace in decision.trace if trace.get("matched")]
    response_payload = PolicySimulationResponse(
        allowed=decision.allowed,
        reason=decision.reason,
        matched_policy_id=decision.matched_policy_id,
        matched_policies=matched_policies,
        trace=decision.trace,
    )

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type=principal.auth_method,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="authz.simulation.run",
        outcome="success" if decision.allowed else "failure",
        resource_type="authorization_policy",
        resource_id=policy.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "resource_type": payload.resource_type,
            "action": payload.action,
            "matched_policy_id": decision.matched_policy_id,
        },
        commit=True,
        best_effort=True,
    )

    return success_response(request=request, data=response_payload)


@router.get(
    "/documents/{document_id}/permissions",
    response_model=SuccessEnvelope[DocumentPermissionList] | DocumentPermissionList,
)
async def list_document_permissions(
    document_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> DocumentPermissionList:
    # List document ACLs for admin inspection.
    await _ensure_document_visible(session=db, tenant_id=principal.tenant_id, document_id=document_id)
    rows = await authz_repo.list_document_permissions(
        db,
        tenant_id=principal.tenant_id,
        document_id=document_id,
    )
    payload = DocumentPermissionList(items=[_permission_payload(row) for row in rows])
    return success_response(request=request, data=payload)


@router.post(
    "/documents/{document_id}/permissions",
    response_model=SuccessEnvelope[DocumentPermissionResponse] | DocumentPermissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def grant_document_permission(
    document_id: str,
    request: Request,
    payload: DocumentPermissionRequest,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> DocumentPermissionResponse:
    # Grant explicit document permissions to principals.
    await _ensure_document_visible(session=db, tenant_id=principal.tenant_id, document_id=document_id)
    request_hash = compute_request_hash(
        {"document_id": document_id, "payload": payload.model_dump()}
    )
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    permission, created = await _grant_permission(
        session=db,
        tenant_id=principal.tenant_id,
        document_id=document_id,
        payload=payload,
        granted_by=principal.api_key_id,
    )
    await db.commit()
    await db.refresh(permission)

    if created:
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type=principal.auth_method,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="authz.permission.granted",
            outcome="success",
            resource_type="document_permission",
            resource_id=permission.id,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={
                "document_id": document_id,
                "principal_type": payload.principal_type,
                "principal_id": payload.principal_id,
                "permission": payload.permission,
            },
            commit=True,
            best_effort=True,
        )

    response_payload = _permission_payload(permission)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=status.HTTP_201_CREATED,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.post(
    "/documents/{document_id}/permissions/bulk",
    response_model=SuccessEnvelope[DocumentPermissionBulkResponse] | DocumentPermissionBulkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_grant_document_permissions(
    document_id: str,
    request: Request,
    payload: DocumentPermissionBulkRequest,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> DocumentPermissionBulkResponse:
    # Grant multiple document permissions in a single request.
    await _ensure_document_visible(session=db, tenant_id=principal.tenant_id, document_id=document_id)
    request_hash = compute_request_hash(
        {"document_id": document_id, "payload": payload.model_dump()}
    )
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    created_permissions: list[DocumentPermission] = []
    for item in payload.permissions:
        permission, created = await _grant_permission(
            session=db,
            tenant_id=principal.tenant_id,
            document_id=document_id,
            payload=item,
            granted_by=principal.api_key_id,
        )
        if created:
            created_permissions.append(permission)
    await db.commit()
    for permission in created_permissions:
        await db.refresh(permission)

    request_ctx = get_request_context(request)
    for permission in created_permissions:
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type=principal.auth_method,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="authz.permission.granted",
            outcome="success",
            resource_type="document_permission",
            resource_id=permission.id,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={
                "document_id": document_id,
                "principal_type": permission.principal_type,
                "principal_id": permission.principal_id,
                "permission": permission.permission,
            },
            commit=True,
            best_effort=True,
        )

    response_payload = DocumentPermissionBulkResponse(
        items=[_permission_payload(permission) for permission in created_permissions]
    )
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=status.HTTP_201_CREATED,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.delete(
    "/documents/{document_id}/permissions/{permission_id}",
    response_model=SuccessEnvelope[DocumentPermissionResponse] | DocumentPermissionResponse,
)
async def revoke_document_permission(
    document_id: str,
    permission_id: str,
    request: Request,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> DocumentPermissionResponse:
    # Revoke document permissions by id.
    await _ensure_document_visible(session=db, tenant_id=principal.tenant_id, document_id=document_id)
    request_hash = compute_request_hash({"document_id": document_id, "permission_id": permission_id})
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    permission = await authz_repo.delete_permission(
        db,
        tenant_id=principal.tenant_id,
        permission_id=permission_id,
    )
    if permission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AUTHZ_PERMISSION_NOT_FOUND", "message": "Permission not found"},
        )
    await db.commit()

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type=principal.auth_method,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="authz.permission.revoked",
        outcome="success",
        resource_type="document_permission",
        resource_id=permission.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "document_id": document_id,
            "principal_type": permission.principal_type,
            "principal_id": permission.principal_id,
            "permission": permission.permission,
        },
        commit=True,
        best_effort=True,
    )

    response_payload = _permission_payload(permission)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=status.HTTP_200_OK,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body
