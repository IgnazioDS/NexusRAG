from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.response import is_versioned_request
from nexusrag.core.config import get_settings
from nexusrag.domain.models import IdempotencyRecord


logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"


@dataclass(frozen=True)
class IdempotencyScope:
    tenant_id: str
    actor_id: str
    method: str
    path: str
    key: str


@dataclass(frozen=True)
class IdempotencyReplay:
    # Capture replay responses so handlers can short-circuit safely.
    status_code: int
    body: Any
    request_id: str | None


@dataclass(frozen=True)
class IdempotencyContext:
    scope: IdempotencyScope
    request_hash: str
    ttl_hours: int


def _normalize_key(value: str) -> str:
    # Enforce idempotency key size constraints for storage safety.
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "IDEMPOTENCY_KEY_INVALID", "message": "Idempotency-Key is empty"},
        )
    if len(cleaned) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "IDEMPOTENCY_KEY_INVALID",
                "message": "Idempotency-Key exceeds 128 characters",
            },
        )
    return cleaned


def compute_request_hash(payload: Any) -> str:
    # Hash request payloads deterministically without persisting sensitive data.
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _expires_at(ttl_hours: int) -> datetime:
    # Use UTC timestamps for consistent TTL boundaries.
    return datetime.now(timezone.utc) + timedelta(hours=ttl_hours)


def _extract_request_id(body: Any) -> str | None:
    # Reuse stored request_id for idempotent replay responses.
    if isinstance(body, dict):
        meta = body.get("meta")
        if isinstance(meta, dict):
            value = meta.get("request_id")
            if isinstance(value, str):
                return value
    return None


def build_replay_response(replay: IdempotencyReplay) -> Response:
    # Return stored responses with a replay marker header for visibility.
    headers = {"Idempotency-Replayed": "true"}
    if replay.request_id:
        headers["X-Request-Id"] = replay.request_id
    if replay.body is None:
        return Response(status_code=replay.status_code, headers=headers)
    response = JSONResponse(content=replay.body, status_code=replay.status_code, headers=headers)
    return response


async def check_idempotency(
    *,
    request: Request,
    db: AsyncSession,
    tenant_id: str,
    actor_id: str,
    request_hash: str,
) -> tuple[IdempotencyContext | None, IdempotencyReplay | None]:
    # Resolve idempotency behavior for versioned write endpoints.
    settings = get_settings()
    if not settings.idempotency_enabled or not is_versioned_request(request):
        return None, None
    raw_key = request.headers.get(IDEMPOTENCY_HEADER)
    if not raw_key:
        return None, None
    key = _normalize_key(raw_key)
    scope = IdempotencyScope(
        tenant_id=tenant_id,
        actor_id=actor_id,
        method=request.method.upper(),
        path=request.url.path,
        key=key,
    )
    try:
        result = await db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == scope.tenant_id,
                IdempotencyRecord.actor_id == scope.actor_id,
                IdempotencyRecord.method == scope.method,
                IdempotencyRecord.path == scope.path,
                IdempotencyRecord.idem_key == scope.key,
                IdempotencyRecord.expires_at > datetime.now(timezone.utc),
            )
        )
    except SQLAlchemyError:
        logger.exception("Failed to lookup idempotency record")
        return IdempotencyContext(scope=scope, request_hash=request_hash, ttl_hours=settings.idempotency_ttl_hours), None
    record = result.scalar_one_or_none()
    if record is None:
        return IdempotencyContext(scope=scope, request_hash=request_hash, ttl_hours=settings.idempotency_ttl_hours), None
    if record.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_KEY_CONFLICT",
                "message": "Idempotency-Key already used with different payload",
            },
        )
    body = record.response_body_json
    return (
        None,
        IdempotencyReplay(
            status_code=record.response_status,
            body=body,
            request_id=_extract_request_id(body),
        ),
    )


async def store_idempotency_response(
    *,
    db: AsyncSession,
    context: IdempotencyContext | None,
    response_status: int,
    response_body: Any,
) -> None:
    # Persist idempotency records after successful handling.
    if context is None:
        return
    record = IdempotencyRecord(
        tenant_id=context.scope.tenant_id,
        actor_id=context.scope.actor_id,
        method=context.scope.method,
        path=context.scope.path,
        idem_key=context.scope.key,
        request_hash=context.request_hash,
        response_status=response_status,
        response_body_json=response_body,
        expires_at=_expires_at(context.ttl_hours),
    )
    try:
        db.add(record)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Failed to persist idempotency record")
