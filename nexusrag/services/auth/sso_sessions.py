from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import SsoSession, TenantUser
from nexusrag.services.auth.api_keys import normalize_role


TOKEN_PREFIX = "nrgss_"


def _utc_now() -> datetime:
    # Keep SSO session timestamps in UTC for consistent expiry checks.
    return datetime.now(timezone.utc)


def is_sso_session_token(raw_token: str) -> bool:
    # Distinguish SSO sessions from API keys to route auth logic safely.
    return raw_token.startswith(TOKEN_PREFIX)


def hash_sso_token(raw_token: str) -> str:
    # Use SHA-256 for deterministic, non-reversible token storage.
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_sso_token() -> tuple[str, str, str, str]:
    # Embed a short id prefix to support operational tracing without plaintext tokens.
    token_id = uuid4().hex
    secret = secrets.token_urlsafe(32)
    raw_token = f"{TOKEN_PREFIX}{token_id}_{secret}"
    token_prefix = raw_token[:12]
    return token_id, raw_token, token_prefix, hash_sso_token(raw_token)


def _unauthorized(message: str) -> HTTPException:
    # Normalize SSO session auth failures with 401 responses.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTH_UNAUTHORIZED", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(message: str) -> HTTPException:
    # Return 403 for authenticated but disabled tenant users.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "AUTH_FORBIDDEN", "message": message},
    )


async def create_sso_session(
    *,
    session: AsyncSession,
    tenant_id: str,
    user_id: str,
    provider_id: str | None,
    ttl_hours: int | None,
) -> tuple[str, SsoSession]:
    # Persist a hashed SSO session token for subsequent API authentication.
    token_id, raw_token, token_prefix, token_hash = generate_sso_token()
    now = _utc_now()
    expires_at = None if ttl_hours is None else now + timedelta(hours=ttl_hours)
    row = SsoSession(
        id=token_id,
        tenant_id=tenant_id,
        user_id=user_id,
        provider_id=provider_id,
        token_prefix=token_prefix,
        token_hash=token_hash,
        created_at=now,
        last_seen_at=None,
        expires_at=expires_at,
        revoked_at=None,
    )
    session.add(row)
    await session.flush()
    return raw_token, row


async def resolve_sso_session(
    *,
    session: AsyncSession,
    raw_token: str,
) -> tuple[SsoSession, TenantUser]:
    # Validate the session token and return the tenant user for authorization.
    token_hash = hash_sso_token(raw_token)
    result = await session.execute(
        select(SsoSession, TenantUser)
        .join(TenantUser, TenantUser.id == SsoSession.user_id)
        .where(SsoSession.token_hash == token_hash)
    )
    row = result.first()
    if row is None:
        raise _unauthorized("Invalid session token")
    sso_session, tenant_user = row
    now = _utc_now()
    if sso_session.revoked_at is not None:
        raise _unauthorized("Session token revoked")
    if sso_session.expires_at is not None and sso_session.expires_at <= now:
        raise _unauthorized("Session token expired")
    if tenant_user.status != "active":
        raise _forbidden("Tenant user is disabled")
    # Normalize role to keep RBAC comparisons stable even for legacy data.
    normalized_role = normalize_role(tenant_user.role)
    if tenant_user.role != normalized_role:
        tenant_user.role = normalized_role
    await session.execute(
        update(SsoSession)
        .where(SsoSession.id == sso_session.id)
        .values(last_seen_at=now)
    )
    return sso_session, tenant_user
