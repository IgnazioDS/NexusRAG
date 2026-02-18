from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.domain.models import ApiKey, User
from nexusrag.services.audit import get_request_context, record_event


router = APIRouter(prefix="/admin/api-keys", tags=["security"], responses=DEFAULT_ERROR_RESPONSES)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AdminApiKeyResponse(BaseModel):
    key_id: str
    key_prefix: str
    name: str | None
    role: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    revoked_at: str | None
    is_active: bool
    is_expired: bool
    inactive_days: int


class AdminApiKeyListResponse(BaseModel):
    tenant_id: str
    inactive_days_threshold: int
    items: list[AdminApiKeyResponse]


class AdminApiKeyPatchRequest(BaseModel):
    # Allow explicit key lifetime tuning without exposing key material.
    expires_at: datetime | None = None
    # Keep this toggle reversible for temporary operational deactivation.
    active: bool | None = None
    # Revoke remains explicit for permanent credential retirement workflows.
    revoke: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)


def _ensure_tenant_scope(principal: Principal, tenant_id: str) -> None:
    # Keep key management tenant-bound to prevent cross-tenant metadata disclosure.
    if tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "AUTH_FORBIDDEN", "message": "Tenant scope does not match admin key"},
        )


def _to_payload(api_key: ApiKey, user: User, now: datetime) -> AdminApiKeyResponse:
    is_expired = api_key.expires_at is not None and api_key.expires_at <= now
    is_active = bool(user.is_active) and api_key.revoked_at is None and not is_expired
    activity_anchor = api_key.last_used_at or api_key.created_at
    inactive_days = max(0, int((now - activity_anchor).days))
    return AdminApiKeyResponse(
        key_id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        role=user.role,
        created_at=api_key.created_at.isoformat(),
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
        revoked_at=api_key.revoked_at.isoformat() if api_key.revoked_at else None,
        is_active=is_active,
        is_expired=is_expired,
        inactive_days=inactive_days,
    )


@router.get(
    "",
    response_model=SuccessEnvelope[AdminApiKeyListResponse] | AdminApiKeyListResponse,
)
async def list_admin_api_keys(
    request: Request,
    tenant_id: str | None = Query(default=None),
    inactive_days: int = Query(default=90, ge=1, le=3650),
    include_only_inactive: bool = Query(default=False),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> AdminApiKeyListResponse:
    # Return key metadata only, with deterministic inactivity calculations for hygiene reports.
    effective_tenant = tenant_id or principal.tenant_id
    _ensure_tenant_scope(principal, effective_tenant)
    try:
        rows = (
            await db.execute(
                select(ApiKey, User)
                .join(User, ApiKey.user_id == User.id)
                .where(ApiKey.tenant_id == effective_tenant)
                .order_by(ApiKey.created_at.desc())
            )
        ).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while listing API keys") from exc

    now = _utc_now()
    threshold = timedelta(days=inactive_days)
    items: list[AdminApiKeyResponse] = []
    for api_key, user in rows:
        payload = _to_payload(api_key, user, now)
        if include_only_inactive and timedelta(days=payload.inactive_days) < threshold and not payload.is_expired:
            continue
        items.append(payload)

    return success_response(
        request=request,
        data=AdminApiKeyListResponse(
            tenant_id=effective_tenant,
            inactive_days_threshold=inactive_days,
            items=items,
        ),
    )


@router.patch(
    "/{key_id}",
    response_model=SuccessEnvelope[AdminApiKeyResponse] | AdminApiKeyResponse,
)
async def patch_admin_api_key(
    key_id: str,
    payload: AdminApiKeyPatchRequest,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> AdminApiKeyResponse:
    # Keep key lifecycle mutations explicit and auditable with a single update endpoint.
    if payload.active is True and payload.revoke:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": "Cannot reactivate and revoke in the same request"},
        )
    try:
        row = (
            await db.execute(
                select(ApiKey, User)
                .join(User, ApiKey.user_id == User.id)
                .where(ApiKey.id == key_id)
                .limit(1)
            )
        ).first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while loading API key") from exc
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "API key not found"})

    api_key, user = row
    _ensure_tenant_scope(principal, api_key.tenant_id)
    now = _utc_now()

    lifecycle_event = "auth.api_key.updated"
    if payload.expires_at is not None:
        api_key.expires_at = payload.expires_at
    if payload.name is not None:
        api_key.name = payload.name
    if payload.active is False and api_key.revoked_at is None:
        # Use revoked_at for deterministic disable semantics without introducing extra lifecycle columns.
        api_key.revoked_at = now
        lifecycle_event = "auth.api_key.deactivated"
    if payload.active is True and not payload.revoke:
        # Reactivation resets activity anchor so inactive-key enforcement can be safely reversed by admins.
        if api_key.revoked_at is not None:
            api_key.revoked_at = None
        api_key.last_used_at = now
        lifecycle_event = "auth.api_key.reactivated"
    if payload.revoke:
        api_key.revoked_at = now
        lifecycle_event = "auth.api_key.revoked"

    try:
        await db.commit()
        await db.refresh(api_key)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while updating API key") from exc

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=api_key.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type=lifecycle_event,
        outcome="success",
        resource_type="api_key",
        resource_id=api_key.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "target_api_key_id": api_key.id,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
            "revoked_at": api_key.revoked_at.isoformat() if api_key.revoked_at else None,
            "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
            "name": api_key.name,
        },
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_to_payload(api_key, user, _utc_now()))
