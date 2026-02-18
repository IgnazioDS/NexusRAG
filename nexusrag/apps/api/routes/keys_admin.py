from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.security import list_platform_keys, retire_platform_key, rotate_platform_key


router = APIRouter(prefix="/admin/keys", tags=["security"], responses=DEFAULT_ERROR_RESPONSES)


class PlatformKeyResponse(BaseModel):
    key_id: str
    purpose: str
    status: str
    created_at: str
    retired_at: str | None


class RotateKeyResponse(BaseModel):
    key: PlatformKeyResponse
    secret: str
    replaced_key_id: str | None


def _to_payload(row) -> PlatformKeyResponse:
    return PlatformKeyResponse(
        key_id=row.key_id,
        purpose=row.purpose,
        status=row.status,
        created_at=row.created_at.isoformat(),
        retired_at=row.retired_at.isoformat() if row.retired_at else None,
    )


@router.get(
    "",
    response_model=SuccessEnvelope[list[PlatformKeyResponse]] | list[PlatformKeyResponse],
)
async def list_keys(
    request: Request,
    purpose: Literal["signing", "encryption"] | None = Query(default=None),
    status: Literal["active", "retired", "revoked"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[PlatformKeyResponse]:
    # Limit key management to tenant admins and expose metadata only (never plaintext secrets).
    _ = principal
    rows = await list_platform_keys(db, purpose=purpose, status=status, limit=limit)
    return success_response(request=request, data=[_to_payload(row) for row in rows])


@router.post(
    "/rotate",
    response_model=SuccessEnvelope[RotateKeyResponse] | RotateKeyResponse,
)
async def rotate_key(
    request: Request,
    purpose: Literal["signing", "encryption"] = Query(...),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RotateKeyResponse:
    # Rotate platform keys with a single active key invariant per purpose.
    row, raw_secret, replaced_key_id = await rotate_platform_key(db, purpose=purpose)
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
        data=RotateKeyResponse(key=_to_payload(row), secret=raw_secret, replaced_key_id=replaced_key_id),
    )


@router.post(
    "/{key_id}/retire",
    response_model=SuccessEnvelope[PlatformKeyResponse] | PlatformKeyResponse,
)
async def retire_key(
    key_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PlatformKeyResponse:
    # Keep retire idempotent and auditable for manual key lifecycle workflows.
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
