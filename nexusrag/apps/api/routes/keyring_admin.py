from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.security import (
    KeyringConfigurationError,
    KeyringDisabledError,
    list_platform_keys,
    retire_platform_key,
    rotate_platform_key,
)


router = APIRouter(prefix="/admin/keyring", tags=["security"], responses=DEFAULT_ERROR_RESPONSES)


class KeyringItemResponse(BaseModel):
    key_id: str
    purpose: str
    status: str
    created_at: str
    activated_at: str | None
    retired_at: str | None


class KeyringRotateResponse(BaseModel):
    key: KeyringItemResponse
    secret: str
    replaced_key_id: str | None


def _raise_keyring_http_error(exc: Exception) -> None:
    # Keep operator failures explicit: required-mode misconfig is server error, optional-mode is disabled.
    if isinstance(exc, KeyringConfigurationError):
        raise HTTPException(
            status_code=500,
            detail={"code": "KEYRING_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    if isinstance(exc, KeyringDisabledError):
        raise HTTPException(
            status_code=503,
            detail={"code": "KEYRING_DISABLED", "message": str(exc)},
        ) from exc
    raise exc


def _to_payload(row) -> KeyringItemResponse:
    return KeyringItemResponse(
        key_id=row.key_id,
        purpose=row.purpose,
        status=row.status,
        created_at=row.created_at.isoformat(),
        activated_at=row.activated_at.isoformat() if row.activated_at else None,
        retired_at=row.retired_at.isoformat() if row.retired_at else None,
    )


@router.get("", response_model=SuccessEnvelope[list[KeyringItemResponse]] | list[KeyringItemResponse])
async def list_keyring(
    request: Request,
    purpose: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[KeyringItemResponse]:
    # Return metadata-only keyring rows so operators can validate lifecycle state without seeing secrets.
    _ = principal
    rows = await list_platform_keys(db, purpose=purpose, status=status, limit=limit)
    return success_response(request=request, data=[_to_payload(row) for row in rows])


@router.post(
    "/rotate",
    response_model=SuccessEnvelope[KeyringRotateResponse] | KeyringRotateResponse,
)
async def rotate_keyring_key(
    request: Request,
    purpose: str = Query(...),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> KeyringRotateResponse:
    # Keep rotation atomic so each purpose has exactly one active key after the transaction.
    try:
        row, raw_secret, replaced_key_id = await rotate_platform_key(db, purpose=purpose)
    except (KeyringConfigurationError, KeyringDisabledError) as exc:
        _raise_keyring_http_error(exc)
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="security.keyring.rotated",
        outcome="success",
        resource_type="platform_key",
        resource_id=row.key_id,
        request_id=request_ctx["request_id"],
        metadata={"purpose": purpose, "replaced_key_id": replaced_key_id},
        commit=True,
        best_effort=True,
    )
    return success_response(
        request=request,
        data=KeyringRotateResponse(key=_to_payload(row), secret=raw_secret, replaced_key_id=replaced_key_id),
    )


@router.post(
    "/{key_id}/retire",
    response_model=SuccessEnvelope[KeyringItemResponse] | KeyringItemResponse,
)
async def retire_keyring_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> KeyringItemResponse:
    # Retire is idempotent and leaves lifecycle evidence intact for compliance exports.
    row = await retire_platform_key(db, key_id=key_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Key not found"})
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="security.keyring.retired",
        outcome="success",
        resource_type="platform_key",
        resource_id=row.key_id,
        request_id=request_ctx["request_id"],
        metadata={"purpose": row.purpose},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_to_payload(row))
