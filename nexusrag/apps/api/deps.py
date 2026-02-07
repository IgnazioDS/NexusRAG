from __future__ import annotations

from typing import AsyncGenerator
import asyncio
import time

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import ApiKey, User
from nexusrag.persistence.db import SessionLocal, get_session
from nexusrag.services.auth.api_keys import hash_api_key, normalize_role, role_allows
from nexusrag.services.audit import get_request_context, record_event


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # One AsyncSession per request; context manager ensures close on success/error.
    async with get_session() as session:
        yield session


class Principal(BaseModel):
    # Capture the authenticated identity used for tenant scoping and RBAC.
    subject_id: str
    tenant_id: str
    role: str
    api_key_id: str


_auth_cache: dict[str, tuple[float, Principal]] = {}
_auth_cache_lock = asyncio.Lock()


def _auth_error(message: str) -> HTTPException:
    # Normalize auth errors for clients without leaking internal details.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTH_UNAUTHORIZED", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden_error(message: str) -> HTTPException:
    # Use 403 for authenticated principals lacking permissions.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "AUTH_FORBIDDEN", "message": message},
    )


def _extract_error_code(exc: HTTPException) -> str | None:
    # Pull stable error codes from HTTPException details for audit entries.
    detail = exc.detail
    if isinstance(detail, dict):
        return detail.get("code")
    return None


def _request_metadata(request: Request) -> dict[str, str]:
    # Include minimal request context for traceability without sensitive headers.
    return {"path": request.url.path, "method": request.method}


async def _get_cached_principal(key_hash: str, ttl_s: int) -> Principal | None:
    # Cache principals briefly to reduce auth DB load between requests.
    if ttl_s <= 0:
        return None
    now = time.time()
    async with _auth_cache_lock:
        entry = _auth_cache.get(key_hash)
        if not entry:
            return None
        expires_at, principal = entry
        if expires_at <= now:
            _auth_cache.pop(key_hash, None)
            return None
        return principal


async def _set_cached_principal(key_hash: str, principal: Principal, ttl_s: int) -> None:
    # Store principals with a fixed expiry to keep revocations responsive.
    if ttl_s <= 0:
        return
    async with _auth_cache_lock:
        _auth_cache[key_hash] = (time.time() + ttl_s, principal)


def _parse_bearer_token(header_value: str | None) -> str | None:
    # Enforce Bearer token format for API key authentication.
    if not header_value:
        return None
    parts = header_value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _auth_error("Missing or invalid bearer token")
    return parts[1]


def _principal_from_dev_headers(request: Request) -> Principal:
    # Allow legacy tenant headers only when explicitly enabled for local dev.
    tenant_id = request.headers.get("X-Tenant-Id")
    if not tenant_id:
        raise _auth_error("X-Tenant-Id header is required in dev bypass mode")
    role_header = request.headers.get("X-Role", "admin")
    try:
        role = normalize_role(role_header)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTH_INVALID_ROLE", "message": str(exc)},
        ) from exc
    return Principal(
        subject_id=f"dev-{tenant_id}",
        tenant_id=tenant_id,
        role=role,
        api_key_id="dev-bypass",
    )


async def reject_tenant_id_in_body(request: Request) -> None:
    # Reject client-supplied tenant_id to enforce credential-bound tenancy.
    content_type = (request.headers.get("content-type") or "").lower()
    if not content_type.startswith("application/json"):
        return
    try:
        payload = await request.json()
    except ValueError:
        return
    if isinstance(payload, dict) and "tenant_id" in payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TENANT_ID_NOT_ALLOWED",
                "message": "tenant_id must be derived from the API key",
            },
        )


async def _touch_last_used(api_key_id: str) -> None:
    # Update last_used_at asynchronously without affecting request transactions.
    async with SessionLocal() as session:
        try:
            await session.execute(
                update(ApiKey)
                .where(ApiKey.id == api_key_id)
                .values(last_used_at=func.now())
            )
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()


async def get_current_principal(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Principal:
    # Emit audit events for auth outcomes without blocking request flow on failures.
    settings = get_settings()
    header_value = request.headers.get(settings.auth_api_key_header)
    try:
        bearer_token = _parse_bearer_token(header_value)
    except HTTPException as exc:
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=None,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="auth.access.failure",
            outcome="failure",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata=_request_metadata(request),
            error_code=_extract_error_code(exc),
            commit=True,
            best_effort=True,
        )
        raise

    if not settings.auth_enabled:
        if settings.auth_dev_bypass:
            principal = _principal_from_dev_headers(request)
            request_ctx = get_request_context(request)
            await record_event(
                session=db,
                tenant_id=principal.tenant_id,
                actor_type="system",
                actor_id=principal.subject_id,
                actor_role=principal.role,
                event_type="auth.access.success",
                outcome="success",
                resource_type="auth",
                request_id=request_ctx["request_id"],
                ip_address=request_ctx["ip_address"],
                user_agent=request_ctx["user_agent"],
                metadata={**_request_metadata(request), "auth_mode": "dev_bypass"},
                commit=True,
                best_effort=True,
            )
            return principal
        exc = _auth_error("Authentication disabled; set AUTH_DEV_BYPASS=true for dev access")
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=None,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="auth.access.failure",
            outcome="failure",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata=_request_metadata(request),
            error_code=_extract_error_code(exc),
            commit=True,
            best_effort=True,
        )
        raise exc

    if not bearer_token:
        if settings.auth_dev_bypass:
            principal = _principal_from_dev_headers(request)
            request_ctx = get_request_context(request)
            await record_event(
                session=db,
                tenant_id=principal.tenant_id,
                actor_type="system",
                actor_id=principal.subject_id,
                actor_role=principal.role,
                event_type="auth.access.success",
                outcome="success",
                resource_type="auth",
                request_id=request_ctx["request_id"],
                ip_address=request_ctx["ip_address"],
                user_agent=request_ctx["user_agent"],
                metadata={**_request_metadata(request), "auth_mode": "dev_bypass"},
                commit=True,
                best_effort=True,
            )
            return principal
        exc = _auth_error("Missing API key")
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=None,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="auth.access.failure",
            outcome="failure",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata=_request_metadata(request),
            error_code=_extract_error_code(exc),
            commit=True,
            best_effort=True,
        )
        raise exc

    key_hash = hash_api_key(bearer_token)
    cached = await _get_cached_principal(key_hash, settings.auth_cache_ttl_s)
    if cached:
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=cached.tenant_id,
            actor_type="api_key",
            actor_id=cached.api_key_id,
            actor_role=cached.role,
            event_type="auth.access.success",
            outcome="success",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={**_request_metadata(request), "auth_cache": True},
            commit=True,
            best_effort=True,
        )
        return cached

    try:
        result = await db.execute(
            select(ApiKey, User)
            .join(User, ApiKey.user_id == User.id)
            .where(ApiKey.key_hash == key_hash)
        )
    except SQLAlchemyError as exc:
        error = HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Authentication unavailable"},
        )
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=None,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type="auth.access.failure",
            outcome="failure",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata=_request_metadata(request),
            error_code=_extract_error_code(error),
            commit=True,
            best_effort=True,
        )
        raise error from exc

    row = result.first()
    if row is None:
        error = _auth_error("Invalid API key")
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=None,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="auth.access.failure",
            outcome="failure",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata=_request_metadata(request),
            error_code=_extract_error_code(error),
            commit=True,
            best_effort=True,
        )
        raise error
    api_key, user = row
    if api_key.revoked_at is not None or not user.is_active:
        error = _auth_error("API key is revoked or inactive")
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=api_key.tenant_id,
            actor_type="api_key",
            actor_id=api_key.id,
            actor_role=user.role,
            event_type="auth.access.failure",
            outcome="failure",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={**_request_metadata(request), "user_id": user.id},
            error_code=_extract_error_code(error),
            commit=True,
            best_effort=True,
        )
        raise error
    if api_key.tenant_id != user.tenant_id:
        error = _forbidden_error("Tenant mismatch for API key")
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=api_key.tenant_id,
            actor_type="api_key",
            actor_id=api_key.id,
            actor_role=user.role,
            event_type="auth.access.failure",
            outcome="failure",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={**_request_metadata(request), "user_id": user.id},
            error_code=_extract_error_code(error),
            commit=True,
            best_effort=True,
        )
        raise error

    try:
        role = normalize_role(user.role)
    except ValueError as exc:
        error = _forbidden_error(str(exc))
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=user.tenant_id,
            actor_type="api_key",
            actor_id=api_key.id,
            actor_role=user.role,
            event_type="auth.access.failure",
            outcome="failure",
            resource_type="auth",
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={**_request_metadata(request), "user_id": user.id},
            error_code=_extract_error_code(error),
            commit=True,
            best_effort=True,
        )
        raise error from exc

    principal = Principal(
        subject_id=user.id,
        tenant_id=user.tenant_id,
        role=role,
        api_key_id=api_key.id,
    )
    await _set_cached_principal(key_hash, principal, settings.auth_cache_ttl_s)
    asyncio.create_task(_touch_last_used(api_key.id))
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="auth.access.success",
        outcome="success",
        resource_type="auth",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={**_request_metadata(request), "user_id": principal.subject_id},
        commit=True,
        best_effort=True,
    )
    return principal


def require_role(minimum_role: str):
    # Dependency factory to enforce RBAC at the route level.
    async def _dependency(
        request: Request,
        principal: Principal = Depends(get_current_principal),
        db: AsyncSession = Depends(get_db),
    ) -> Principal:
        if not role_allows(role=principal.role, minimum_role=minimum_role):
            # Log RBAC denials before raising a 403 response.
            request_ctx = get_request_context(request)
            await record_event(
                session=db,
                tenant_id=principal.tenant_id,
                actor_type="api_key",
                actor_id=principal.api_key_id,
                actor_role=principal.role,
                event_type="rbac.forbidden",
                outcome="failure",
                resource_type="rbac",
                request_id=request_ctx["request_id"],
                ip_address=request_ctx["ip_address"],
                user_agent=request_ctx["user_agent"],
                metadata={**_request_metadata(request), "required_role": minimum_role},
                error_code="AUTH_FORBIDDEN",
                commit=True,
                best_effort=True,
            )
            raise _forbidden_error("Insufficient role for this operation")
        return principal

    return _dependency
