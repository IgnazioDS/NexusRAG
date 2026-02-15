from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.domain.models import KeyRotationJob, TenantKey
from nexusrag.services.audit import record_event
from nexusrag.services.crypto import (
    cancel_rotation_job,
    create_rotation_job,
    get_active_key,
    pause_rotation_job,
    resume_rotation_job,
    rotate_key,
    run_rotation_job,
)


router = APIRouter(prefix="/admin/crypto", tags=["crypto"], responses=DEFAULT_ERROR_RESPONSES)


class TenantKeyResponse(BaseModel):
    id: int
    tenant_id: str
    key_alias: str
    key_version: int
    provider: str
    key_ref: str
    status: str
    created_at: datetime | None
    activated_at: datetime | None
    retired_at: datetime | None


class TenantKeyListResponse(BaseModel):
    tenant_id: str
    active_key_id: int | None
    keys: list[TenantKeyResponse]


class RotateKeyRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    reencrypt: bool = True
    force: bool = False


class RotationJobResponse(BaseModel):
    id: int
    tenant_id: str
    status: str
    from_key_id: int
    to_key_id: int
    total_items: int
    processed_items: int
    failed_items: int
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None


def _ensure_tenant_scope(principal: Principal, tenant_id: str) -> None:
    if tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_FORBIDDEN", "message": "Cross-tenant crypto access denied"},
        )


def _key_payload(row: TenantKey) -> TenantKeyResponse:
    return TenantKeyResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        key_alias=row.key_alias,
        key_version=row.key_version,
        provider=row.provider,
        key_ref=row.key_ref,
        status=row.status,
        created_at=row.created_at,
        activated_at=row.activated_at,
        retired_at=row.retired_at,
    )


def _job_payload(job: KeyRotationJob) -> RotationJobResponse:
    return RotationJobResponse(
        id=job.id,
        tenant_id=job.tenant_id,
        status=job.status,
        from_key_id=job.from_key_id,
        to_key_id=job.to_key_id,
        total_items=job.total_items,
        processed_items=job.processed_items,
        failed_items=job.failed_items,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_code=job.error_code,
        error_message=job.error_message,
    )


@router.get(
    "/keys/{tenant_id}",
    response_model=SuccessEnvelope[TenantKeyListResponse] | TenantKeyListResponse,
)
async def list_tenant_keys(
    request: Request,
    tenant_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> TenantKeyListResponse:
    # Surface tenant key versions for rotation decisions.
    _ensure_tenant_scope(principal, tenant_id)
    rows = (
        await db.execute(
            select(TenantKey)
            .where(TenantKey.tenant_id == tenant_id)
            .order_by(TenantKey.key_version.desc())
        )
    ).scalars().all()
    active_key = next((row for row in rows if row.status == "active"), None)
    payload = TenantKeyListResponse(
        tenant_id=tenant_id,
        active_key_id=active_key.id if active_key else None,
        keys=[_key_payload(row) for row in rows],
    )
    return success_response(request=request, data=payload)


@router.post(
    "/keys/{tenant_id}/rotate",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def rotate_tenant_key(
    request: Request,
    tenant_id: str,
    payload: RotateKeyRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Rotate tenant keys and optionally re-encrypt existing artifacts.
    _ensure_tenant_scope(principal, tenant_id)
    active_job = (
        await db.execute(
            select(KeyRotationJob)
            .where(KeyRotationJob.tenant_id == tenant_id, KeyRotationJob.status.in_(["queued", "running", "paused"]))
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_job is not None:
        if payload.force:
            await cancel_rotation_job(db, job=active_job)
        else:
            raise HTTPException(
                status_code=409,
                detail={"code": "KEY_ROTATION_IN_PROGRESS", "message": "Key rotation already in progress"},
            )
    from_key = await get_active_key(db, tenant_id)
    new_key = await rotate_key(
        db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        reason=payload.reason,
    )
    await record_event(
        session=db,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="crypto.rotation.started",
        outcome="success",
        resource_type="tenant_key",
        resource_id=str(new_key.id),
        metadata={"reason": payload.reason, "reencrypt": payload.reencrypt},
        commit=True,
        best_effort=True,
    )
    job_payload: RotationJobResponse | None = None
    if payload.reencrypt:
        job = await create_rotation_job(db, tenant_id=tenant_id, from_key_id=from_key.id, to_key_id=new_key.id)
        job = await run_rotation_job(db, job=job)
        job_payload = _job_payload(job)
        await record_event(
            session=db,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="crypto.rotation.completed" if job.status == "completed" else "crypto.rotation.failed",
            outcome="success" if job.status == "completed" else "failure",
            resource_type="key_rotation_job",
            resource_id=str(job.id),
            metadata={"processed": job.processed_items, "failed": job.failed_items},
            error_code=job.error_code,
            commit=True,
            best_effort=True,
        )
    return success_response(
        request=request,
        data={"key": _key_payload(new_key), "rotation_job": job_payload},
    )


@router.get(
    "/rotation-jobs/{job_id}",
    response_model=SuccessEnvelope[RotationJobResponse] | RotationJobResponse,
)
async def get_rotation_job(
    request: Request,
    job_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RotationJobResponse:
    # Expose rotation job progress for operator monitoring.
    job = await db.get(KeyRotationJob, job_id)
    if job is None or job.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Rotation job not found"})
    return success_response(request=request, data=_job_payload(job))


@router.post(
    "/rotation-jobs/{job_id}/pause",
    response_model=SuccessEnvelope[RotationJobResponse] | RotationJobResponse,
)
async def pause_rotation(
    request: Request,
    job_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RotationJobResponse:
    # Allow operators to pause long-running rotations.
    job = await db.get(KeyRotationJob, job_id)
    if job is None or job.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Rotation job not found"})
    job = await pause_rotation_job(db, job=job)
    return success_response(request=request, data=_job_payload(job))


@router.post(
    "/rotation-jobs/{job_id}/resume",
    response_model=SuccessEnvelope[RotationJobResponse] | RotationJobResponse,
)
async def resume_rotation(
    request: Request,
    job_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RotationJobResponse:
    # Resume paused rotations without starting a new job.
    job = await db.get(KeyRotationJob, job_id)
    if job is None or job.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Rotation job not found"})
    job = await resume_rotation_job(db, job=job)
    return success_response(request=request, data=_job_payload(job))


@router.post(
    "/rotation-jobs/{job_id}/cancel",
    response_model=SuccessEnvelope[RotationJobResponse] | RotationJobResponse,
)
async def cancel_rotation(
    request: Request,
    job_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RotationJobResponse:
    # Cancel rotations with a terminal failed state.
    job = await db.get(KeyRotationJob, job_id)
    if job is None or job.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Rotation job not found"})
    job = await cancel_rotation_job(db, job=job)
    return success_response(request=request, data=_job_payload(job))
