from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.domain.models import DsarRequest, EncryptedBlob, GovernanceRetentionRun, LegalHold, PolicyRule
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.crypto import decrypt_blob
from nexusrag.services.governance import (
    LEGAL_HOLD_SCOPE_BACKUP_SET,
    LEGAL_HOLD_SCOPE_DOCUMENT,
    LEGAL_HOLD_SCOPE_SESSION,
    LEGAL_HOLD_SCOPE_TENANT,
    LEGAL_HOLD_SCOPE_USER_KEY,
    create_legal_hold,
    get_or_create_retention_policy,
    get_retention_run,
    release_legal_hold,
    run_retention_for_tenant,
    submit_dsar_request,
)


router = APIRouter(prefix="/admin/governance", tags=["governance"], responses=DEFAULT_ERROR_RESPONSES)


class RetentionRunResponse(BaseModel):
    id: int
    tenant_id: str
    status: str
    started_at: str
    completed_at: str | None
    report_json: dict[str, Any] | None
    error_code: str | None
    error_message: str | None


class RetentionPolicyResponse(BaseModel):
    tenant_id: str
    messages_ttl_days: int | None
    checkpoints_ttl_days: int | None
    audit_ttl_days: int | None
    documents_ttl_days: int | None
    backups_ttl_days: int | None
    hard_delete_enabled: bool
    anonymize_instead_of_delete: bool


class RetentionPolicyPatchRequest(BaseModel):
    messages_ttl_days: int | None = Field(default=None, ge=1)
    checkpoints_ttl_days: int | None = Field(default=None, ge=1)
    audit_ttl_days: int | None = Field(default=None, ge=1)
    documents_ttl_days: int | None = Field(default=None, ge=1)
    backups_ttl_days: int | None = Field(default=None, ge=1)
    hard_delete_enabled: bool | None = None
    anonymize_instead_of_delete: bool | None = None


class LegalHoldCreateRequest(BaseModel):
    scope_type: str = Field(pattern="^(tenant|document|session|user_key|backup_set)$")
    scope_id: str | None = None
    reason: str = Field(min_length=3, max_length=500)
    expires_at: datetime | None = None


class LegalHoldResponse(BaseModel):
    id: int
    tenant_id: str
    scope_type: str
    scope_id: str | None
    reason: str
    created_by_actor_id: str | None
    created_at: str
    expires_at: str | None
    is_active: bool


class DsarCreateRequest(BaseModel):
    request_type: str = Field(pattern="^(export|delete|anonymize)$")
    subject_type: str = Field(pattern="^(api_key|session|document|tenant)$")
    subject_id: str
    reason: str | None = None


class DsarResponse(BaseModel):
    id: int
    tenant_id: str
    request_type: str
    subject_type: str
    subject_id: str
    status: str
    artifact_uri: str | None
    report_json: dict[str, Any] | None
    created_at: str
    updated_at: str
    completed_at: str | None
    error_code: str | None
    error_message: str | None


class PolicyRuleRequest(BaseModel):
    rule_key: str = Field(min_length=3, max_length=120)
    enabled: bool = True
    priority: int = Field(default=100, ge=-1000, le=1000)
    condition_json: dict[str, Any] = Field(default_factory=dict)
    action_json: dict[str, Any] = Field(default_factory=dict)


class PolicyRulePatchRequest(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=-1000, le=1000)
    condition_json: dict[str, Any] | None = None
    action_json: dict[str, Any] | None = None


class PolicyRuleResponse(BaseModel):
    id: int
    tenant_id: str | None
    rule_key: str
    enabled: bool
    priority: int
    condition_json: dict[str, Any]
    action_json: dict[str, Any]
    created_at: str
    updated_at: str


def _ensure_same_tenant(principal: Principal, tenant_id: str) -> None:
    # Keep governance operations strictly tenant-scoped for now.
    if tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_FORBIDDEN", "message": "Tenant scope does not match admin key"},
        )


def _retention_response(run: GovernanceRetentionRun) -> RetentionRunResponse:
    return RetentionRunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        status=run.status,
        started_at=run.started_at.isoformat() if run.started_at else "",
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        report_json=run.report_json,
        error_code=run.error_code,
        error_message=run.error_message,
    )


def _retention_policy_response(policy) -> RetentionPolicyResponse:
    return RetentionPolicyResponse(
        tenant_id=policy.tenant_id,
        messages_ttl_days=policy.messages_ttl_days,
        checkpoints_ttl_days=policy.checkpoints_ttl_days,
        audit_ttl_days=policy.audit_ttl_days,
        documents_ttl_days=policy.documents_ttl_days,
        backups_ttl_days=policy.backups_ttl_days,
        hard_delete_enabled=policy.hard_delete_enabled,
        anonymize_instead_of_delete=policy.anonymize_instead_of_delete,
    )


def _hold_response(hold: LegalHold) -> LegalHoldResponse:
    return LegalHoldResponse(
        id=hold.id,
        tenant_id=hold.tenant_id,
        scope_type=hold.scope_type,
        scope_id=hold.scope_id,
        reason=hold.reason,
        created_by_actor_id=hold.created_by_actor_id,
        created_at=hold.created_at.isoformat() if hold.created_at else "",
        expires_at=hold.expires_at.isoformat() if hold.expires_at else None,
        is_active=hold.is_active,
    )


def _dsar_response(row: DsarRequest) -> DsarResponse:
    return DsarResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        request_type=row.request_type,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        status=row.status,
        artifact_uri=row.artifact_uri,
        report_json=row.report_json,
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        error_code=row.error_code,
        error_message=row.error_message,
    )


@router.get(
    "/retention/policy",
    response_model=SuccessEnvelope[RetentionPolicyResponse] | RetentionPolicyResponse,
)
async def get_retention_policy(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RetentionPolicyResponse:
    # Expose tenant retention settings used by governance maintenance jobs.
    policy = await get_or_create_retention_policy(db, principal.tenant_id)
    return success_response(request=request, data=_retention_policy_response(policy))


@router.patch(
    "/retention/policy",
    response_model=SuccessEnvelope[RetentionPolicyResponse] | RetentionPolicyResponse,
)
async def patch_retention_policy(
    request: Request,
    payload: RetentionPolicyPatchRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RetentionPolicyResponse:
    # Allow tenant admins to tune retention TTLs and deletion mode.
    policy = await get_or_create_retention_policy(db, principal.tenant_id)
    if payload.messages_ttl_days is not None:
        policy.messages_ttl_days = payload.messages_ttl_days
    if payload.checkpoints_ttl_days is not None:
        policy.checkpoints_ttl_days = payload.checkpoints_ttl_days
    if payload.audit_ttl_days is not None:
        policy.audit_ttl_days = payload.audit_ttl_days
    if payload.documents_ttl_days is not None:
        policy.documents_ttl_days = payload.documents_ttl_days
    if payload.backups_ttl_days is not None:
        policy.backups_ttl_days = payload.backups_ttl_days
    if payload.hard_delete_enabled is not None:
        policy.hard_delete_enabled = payload.hard_delete_enabled
    if payload.anonymize_instead_of_delete is not None:
        policy.anonymize_instead_of_delete = payload.anonymize_instead_of_delete
    await db.commit()
    await db.refresh(policy)
    return success_response(request=request, data=_retention_policy_response(policy))


@router.post(
    "/retention/run",
    response_model=SuccessEnvelope[RetentionRunResponse] | RetentionRunResponse,
)
async def run_retention(
    request: Request,
    tenant_id: str | None = Query(default=None),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RetentionRunResponse:
    # Allow tenant admins to trigger bounded retention runs on demand.
    effective_tenant = tenant_id or principal.tenant_id
    _ensure_same_tenant(principal, effective_tenant)
    request_ctx = get_request_context(request)
    run = await run_retention_for_tenant(
        session=db,
        tenant_id=effective_tenant,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        request_id=request_ctx["request_id"],
    )
    return success_response(request=request, data=_retention_response(run))


@router.get(
    "/retention/report",
    response_model=SuccessEnvelope[RetentionRunResponse] | RetentionRunResponse,
)
async def get_retention_report(
    request: Request,
    run_id: int = Query(..., ge=1),
    tenant_id: str | None = Query(default=None),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RetentionRunResponse:
    # Return a single retention run report for evidence inspection.
    effective_tenant = tenant_id or principal.tenant_id
    _ensure_same_tenant(principal, effective_tenant)
    run = await get_retention_run(db, tenant_id=effective_tenant, run_id=run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Retention report not found"},
        )
    return success_response(request=request, data=_retention_response(run))


@router.post(
    "/legal-holds",
    response_model=SuccessEnvelope[LegalHoldResponse] | LegalHoldResponse,
)
async def create_hold(
    request: Request,
    payload: LegalHoldCreateRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> LegalHoldResponse:
    # Create legal holds used by retention/DSAR enforcement paths.
    if payload.scope_type == LEGAL_HOLD_SCOPE_TENANT and payload.scope_id is not None:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "scope_id must be null for tenant scope"},
        )
    if payload.scope_type in {
        LEGAL_HOLD_SCOPE_DOCUMENT,
        LEGAL_HOLD_SCOPE_SESSION,
        LEGAL_HOLD_SCOPE_USER_KEY,
        LEGAL_HOLD_SCOPE_BACKUP_SET,
    } and not payload.scope_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "scope_id is required for scoped holds"},
        )
    request_ctx = get_request_context(request)
    hold = await create_legal_hold(
        session=db,
        tenant_id=principal.tenant_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        reason=payload.reason,
        expires_at=payload.expires_at,
        created_by_actor_id=principal.api_key_id,
        actor_role=principal.role,
        request_id=request_ctx["request_id"],
    )
    return success_response(request=request, data=_hold_response(hold))


@router.get(
    "/legal-holds",
    response_model=SuccessEnvelope[list[LegalHoldResponse]] | list[LegalHoldResponse],
)
async def list_holds(
    request: Request,
    active: bool = Query(default=True),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[LegalHoldResponse]:
    # Return hold state for tenant admin investigations.
    query = select(LegalHold).where(LegalHold.tenant_id == principal.tenant_id)
    if active:
        query = query.where(LegalHold.is_active.is_(True))
    rows = (await db.execute(query.order_by(LegalHold.created_at.desc()))).scalars().all()
    payload = [_hold_response(row) for row in rows]
    return success_response(request=request, data=payload)


@router.post(
    "/legal-holds/{hold_id}/release",
    response_model=SuccessEnvelope[LegalHoldResponse] | LegalHoldResponse,
)
async def release_hold(
    hold_id: int,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> LegalHoldResponse:
    # Release holds idempotently while keeping audit history intact.
    hold = await db.get(LegalHold, hold_id)
    if hold is None or hold.tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Legal hold not found"},
        )
    request_ctx = get_request_context(request)
    hold = await release_legal_hold(
        session=db,
        hold=hold,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        request_id=request_ctx["request_id"],
    )
    return success_response(request=request, data=_hold_response(hold))


@router.post(
    "/dsar",
    response_model=SuccessEnvelope[DsarResponse] | DsarResponse,
)
async def create_dsar(
    request: Request,
    payload: DsarCreateRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> DsarResponse:
    # Submit and execute DSAR requests with policy/hold enforcement.
    request_ctx = get_request_context(request)
    row = await submit_dsar_request(
        session=db,
        tenant_id=principal.tenant_id,
        request_type=payload.request_type,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        reason=payload.reason,
        requested_by_actor_id=principal.api_key_id,
        actor_role=principal.role,
        request_id=request_ctx["request_id"],
    )
    return success_response(request=request, data=_dsar_response(row))


@router.get(
    "/dsar/{dsar_id}",
    response_model=SuccessEnvelope[DsarResponse] | DsarResponse,
)
async def get_dsar(
    request: Request,
    dsar_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> DsarResponse:
    # Fetch DSAR status for polling and incident timelines.
    row = await db.get(DsarRequest, dsar_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "DSAR_NOT_FOUND", "message": "DSAR request not found"},
        )
    return success_response(request=request, data=_dsar_response(row))


@router.get("/dsar/{dsar_id}/artifact", response_class=Response, response_model=None)
async def get_dsar_artifact(
    dsar_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Return export artifacts only for completed export requests in the same tenant.
    row = await db.get(DsarRequest, dsar_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "DSAR_NOT_FOUND", "message": "DSAR request not found"},
        )
    if row.request_type != "export" or row.status != "completed" or not row.artifact_uri:
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": "DSAR export artifact is not available"},
        )
    if row.artifact_uri.startswith("encrypted_blob:"):
        blob_id = int(row.artifact_uri.split(":", 1)[1])
        blob = await db.get(EncryptedBlob, blob_id)
        if blob is None or blob.tenant_id != principal.tenant_id:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "DSAR artifact not found"},
            )
        payload = await decrypt_blob(db, blob=blob)
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="crypto.decrypt.accessed",
            outcome="success",
            resource_type="dsar_artifact",
            resource_id=str(dsar_id),
            metadata={"artifact_uri": row.artifact_uri},
            commit=True,
            best_effort=True,
        )
        return Response(content=payload, media_type="application/gzip")
    artifact = Path(row.artifact_uri)
    if not artifact.exists():
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "DSAR artifact not found"},
        )
    return FileResponse(path=artifact, filename=artifact.name, media_type="application/gzip")


@router.get(
    "/policies",
    response_model=SuccessEnvelope[list[PolicyRuleResponse]] | list[PolicyRuleResponse],
)
async def list_policies(
    request: Request,
    rule_key: str | None = None,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[PolicyRuleResponse]:
    # Expose tenant+global rules so admins can inspect effective governance logic.
    query = select(PolicyRule).where(
        (PolicyRule.tenant_id == principal.tenant_id) | (PolicyRule.tenant_id.is_(None))
    )
    if rule_key:
        query = query.where(PolicyRule.rule_key == rule_key)
    rows = (await db.execute(query.order_by(PolicyRule.priority.desc(), PolicyRule.id.asc()))).scalars().all()
    payload = [
        PolicyRuleResponse(
            id=row.id,
            tenant_id=row.tenant_id,
            rule_key=row.rule_key,
            enabled=row.enabled,
            priority=row.priority,
            condition_json=row.condition_json or {},
            action_json=row.action_json or {},
            created_at=row.created_at.isoformat() if row.created_at else "",
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
        )
        for row in rows
    ]
    return success_response(request=request, data=payload)


@router.post(
    "/policies",
    response_model=SuccessEnvelope[PolicyRuleResponse] | PolicyRuleResponse,
)
async def create_policy(
    request: Request,
    payload: PolicyRuleRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyRuleResponse:
    # Create tenant-scoped governance rules for policy-as-code controls.
    row = PolicyRule(
        tenant_id=principal.tenant_id,
        rule_key=payload.rule_key,
        enabled=payload.enabled,
        priority=payload.priority,
        condition_json=payload.condition_json,
        action_json=payload.action_json,
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
        event_type="governance.policy.updated",
        outcome="success",
        resource_type="policy_rule",
        resource_id=str(row.id),
        request_id=request_ctx["request_id"],
        metadata={"rule_key": row.rule_key, "action_json": row.action_json},
        commit=True,
        best_effort=True,
    )
    payload_out = PolicyRuleResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        rule_key=row.rule_key,
        enabled=row.enabled,
        priority=row.priority,
        condition_json=row.condition_json or {},
        action_json=row.action_json or {},
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )
    return success_response(request=request, data=payload_out)


@router.patch(
    "/policies/{policy_id}",
    response_model=SuccessEnvelope[PolicyRuleResponse] | PolicyRuleResponse,
)
async def patch_policy(
    policy_id: int,
    request: Request,
    payload: PolicyRulePatchRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyRuleResponse:
    # Update tenant-scoped governance rules without exposing cross-tenant records.
    row = await db.get(PolicyRule, policy_id)
    if row is None or row.tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Policy rule not found"},
        )
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.priority is not None:
        row.priority = payload.priority
    if payload.condition_json is not None:
        row.condition_json = payload.condition_json
    if payload.action_json is not None:
        row.action_json = payload.action_json
    await db.commit()
    await db.refresh(row)
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="governance.policy.updated",
        outcome="success",
        resource_type="policy_rule",
        resource_id=str(row.id),
        request_id=request_ctx["request_id"],
        metadata={"rule_key": row.rule_key, "action_json": row.action_json},
        commit=True,
        best_effort=True,
    )
    payload_out = PolicyRuleResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        rule_key=row.rule_key,
        enabled=row.enabled,
        priority=row.priority,
        condition_json=row.condition_json or {},
        action_json=row.action_json or {},
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )
    return success_response(request=request, data=payload_out)
