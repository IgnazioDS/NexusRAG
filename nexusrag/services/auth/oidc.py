from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import json
import logging
import secrets
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
import asyncio
import time

import httpx
import jwt
from sqlalchemy import select

from nexusrag.core.config import get_settings
from nexusrag.domain.models import IdentityProvider, ScimGroup, ScimGroupMembership, TenantUser
from nexusrag.services.auth.api_keys import ROLE_ORDER, normalize_role
from nexusrag.services.resilience import get_resilience_redis


logger = logging.getLogger(__name__)

_ALLOWED_ALGS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}

_STATE_PREFIX = "nexusrag:sso:state:"
_NONCE_PREFIX = "nexusrag:sso:nonce:"
_state_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_nonce_cache: dict[str, float] = {}
_cache_lock = asyncio.Lock()


@dataclass(frozen=True)
class OidcClaims:
    subject: str
    email: str | None
    name: str | None
    groups: list[str]
    raw: dict[str, Any]


@dataclass(frozen=True)
class OidcTokenResponse:
    id_token: str
    access_token: str | None
    token_type: str | None
    expires_in: int | None


class JitProvisioningDisabled(Exception):
    # Signal JIT provisioning is disabled for the provider or tenant.
    pass


class TenantUserDisabled(Exception):
    # Signal tenant users are disabled and cannot login.
    pass


def _utc_now() -> datetime:
    # Keep OIDC timestamps aligned to UTC for token validation.
    return datetime.now(timezone.utc)


def _base64url_encode(raw: bytes) -> str:
    # Produce base64url strings without padding for PKCE.
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("utf-8")


def generate_state() -> str:
    # Use a cryptographically secure nonce for OIDC state.
    return _base64url_encode(secrets.token_bytes(32))


def generate_nonce() -> str:
    # Generate a cryptographically secure nonce for ID token replay protection.
    return _base64url_encode(secrets.token_bytes(32))


def generate_pkce_verifier() -> str:
    # Create a PKCE verifier suitable for S256 challenges.
    return _base64url_encode(secrets.token_bytes(32))


def build_code_challenge(verifier: str) -> str:
    # Hash PKCE verifier to generate the S256 code challenge.
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return _base64url_encode(digest)


def build_authorize_url(
    *,
    provider: IdentityProvider,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    # Construct the authorization URL for the configured provider.
    scopes = provider.scopes_json or ["openid", "email", "profile"]
    query = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{provider.auth_url}?{urlencode(query)}"


def append_query_params(url: str, params: dict[str, str]) -> str:
    # Safely append query params to redirect URLs without clobbering existing data.
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query.update(params)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _state_key(state: str) -> str:
    # Namespace state keys to avoid collisions with other Redis data.
    return f"{_STATE_PREFIX}{state}"


def _nonce_key(nonce: str) -> str:
    # Namespace nonce keys to avoid collisions with other Redis data.
    return f"{_NONCE_PREFIX}{nonce}"


async def store_state(*, state: str, payload: dict[str, Any], ttl_seconds: int) -> None:
    # Persist OIDC state in Redis with TTL, falling back to in-memory for tests.
    redis = await get_resilience_redis()
    if redis is None:
        async with _cache_lock:
            _state_cache[state] = (time.time() + ttl_seconds, payload)
        return
    await redis.setex(_state_key(state), ttl_seconds, json.dumps(payload))


async def pop_state(state: str) -> dict[str, Any] | None:
    # Fetch and delete state payload to enforce single use.
    redis = await get_resilience_redis()
    if redis is None:
        async with _cache_lock:
            entry = _state_cache.pop(state, None)
        if not entry:
            return None
        expires_at, payload = entry
        if expires_at <= time.time():
            return None
        return payload
    raw = await redis.get(_state_key(state))
    if raw is None:
        return None
    await redis.delete(_state_key(state))
    return json.loads(raw)


async def store_nonce(*, nonce: str, ttl_seconds: int) -> None:
    # Persist nonce values with TTL to prevent replay attacks.
    redis = await get_resilience_redis()
    if redis is None:
        async with _cache_lock:
            _nonce_cache[nonce] = time.time() + ttl_seconds
        return
    await redis.setex(_nonce_key(nonce), ttl_seconds, "1")


async def pop_nonce(nonce: str) -> bool:
    # Enforce one-time use of nonces to guard against token replay.
    redis = await get_resilience_redis()
    if redis is None:
        async with _cache_lock:
            expires_at = _nonce_cache.pop(nonce, None)
        if expires_at is None or expires_at <= time.time():
            return False
        return True
    exists = await redis.get(_nonce_key(nonce))
    if exists is None:
        return False
    await redis.delete(_nonce_key(nonce))
    return True


def extract_claims(claims: dict[str, Any]) -> OidcClaims:
    # Normalize identity claims for downstream provisioning and role mapping.
    subject = claims.get("sub") or claims.get("nameid")
    if not subject:
        raise ValueError("ID token missing subject")
    email = claims.get("email") or claims.get("upn") or claims.get("preferred_username")
    name = claims.get("name")
    if not name:
        given = claims.get("given_name")
        family = claims.get("family_name")
        if given or family:
            name = " ".join([part for part in [given, family] if part])
    raw_groups = claims.get("groups") or claims.get("roles") or claims.get("role")
    groups = _normalize_list_claim(raw_groups)
    return OidcClaims(subject=str(subject), email=email, name=name, groups=groups, raw=claims)


def _normalize_list_claim(value: Any) -> list[str]:
    # Coerce claim values into a list of strings for mapping.
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _select_highest_role(roles: list[str]) -> str | None:
    # Pick the highest privilege role based on configured RBAC ordering.
    normalized: list[str] = []
    for role in roles:
        if not role:
            continue
        try:
            normalized.append(normalize_role(role))
        except ValueError:
            continue
    if not normalized:
        return None
    return max(normalized, key=lambda role: ROLE_ORDER.get(role, 0))


def resolve_role_from_claims(mapping: dict[str, Any] | None, claims: OidcClaims) -> str | None:
    # Map OIDC claim values to RBAC roles using provider-defined rules.
    if not mapping:
        return None
    roles: list[str] = []
    if isinstance(mapping, dict) and "claim" in mapping and "mapping" in mapping:
        claim_name = str(mapping.get("claim"))
        claim_map = mapping.get("mapping") or {}
        claim_values = _normalize_list_claim(claims.raw.get(claim_name))
        for value in claim_values:
            mapped = claim_map.get(value)
            if mapped:
                roles.append(mapped)
    elif isinstance(mapping, dict):
        for claim_name, claim_map in mapping.items():
            if not isinstance(claim_map, dict):
                continue
            claim_values = _normalize_list_claim(claims.raw.get(claim_name))
            for value in claim_values:
                mapped = claim_map.get(value)
                if mapped:
                    roles.append(mapped)
    return _select_highest_role(roles)


async def resolve_role_from_scim(
    *,
    session,
    tenant_id: str,
    user_id: str,
) -> str | None:
    # Prefer explicit SCIM group bindings when available.
    result = await session.execute(
        select(ScimGroup.role_binding)
        .join(ScimGroupMembership, ScimGroupMembership.group_id == ScimGroup.id)
        .where(
            ScimGroupMembership.user_id == user_id,
            ScimGroup.tenant_id == tenant_id,
            ScimGroup.role_binding.isnot(None),
        )
    )
    roles = [row[0] for row in result.fetchall() if row[0]]
    return _select_highest_role(roles)


async def exchange_code_for_tokens(
    *,
    provider: IdentityProvider,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> OidcTokenResponse:
    # Exchange authorization code for tokens via the provider token endpoint.
    settings = get_settings()
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "client_secret": resolve_client_secret(provider.client_secret_ref),
        "code_verifier": code_verifier,
    }
    timeout = settings.ext_call_timeout_ms / 1000
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(provider.token_url, data=payload)
    if response.status_code >= 400:
        logger.warning("oidc_token_exchange_failed status=%s", response.status_code)
        raise ValueError("Token exchange failed")
    body = response.json()
    id_token = body.get("id_token")
    if not id_token:
        raise ValueError("Token exchange response missing id_token")
    return OidcTokenResponse(
        id_token=id_token,
        access_token=body.get("access_token"),
        token_type=body.get("token_type"),
        expires_in=body.get("expires_in"),
    )


def resolve_client_secret(client_secret_ref: str) -> str:
    # Resolve secret references from environment variables for now.
    try:
        import os

        env_secret = os.getenv(client_secret_ref)
    except Exception:
        env_secret = None
    if env_secret:
        return env_secret
    raise ValueError("Client secret reference not found")


async def _fetch_jwks(jwks_url: str) -> dict[str, Any]:
    # Fetch JWKS from the provider for signature verification.
    settings = get_settings()
    timeout = settings.ext_call_timeout_ms / 1000
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(jwks_url)
    response.raise_for_status()
    return response.json()


def _select_jwk(jwks: dict[str, Any], kid: str | None) -> dict[str, Any]:
    # Select the appropriate JWK based on kid header.
    keys = jwks.get("keys") or []
    if kid:
        for key in keys:
            if key.get("kid") == kid:
                return key
    if len(keys) == 1:
        return keys[0]
    raise ValueError("No matching JWK for token")


def _jwk_to_key(jwk: dict[str, Any], alg: str) -> Any:
    # Convert a JWK payload into a cryptography key for PyJWT.
    payload = json.dumps(jwk)
    if alg.startswith("RS"):
        return jwt.algorithms.RSAAlgorithm.from_jwk(payload)
    if alg.startswith("ES"):
        return jwt.algorithms.ECAlgorithm.from_jwk(payload)
    raise ValueError("Unsupported JWT algorithm")


async def validate_id_token(
    *,
    provider: IdentityProvider,
    token: str,
    nonce: str,
    clock_skew_seconds: int,
) -> dict[str, Any]:
    # Validate the ID token signature and core claims.
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    if not alg or alg not in _ALLOWED_ALGS:
        raise ValueError("Unsupported token algorithm")
    jwks = await _fetch_jwks(provider.jwks_url)
    jwk = _select_jwk(jwks, header.get("kid"))
    key = _jwk_to_key(jwk, alg)
    claims = jwt.decode(
        token,
        key,
        algorithms=[alg],
        audience=provider.client_id,
        issuer=provider.issuer,
        leeway=clock_skew_seconds,
    )
    if claims.get("nonce") != nonce:
        raise ValueError("Nonce mismatch")
    return claims


async def resolve_role(
    *,
    session,
    provider: IdentityProvider,
    claims: OidcClaims,
    tenant_id: str,
    user: TenantUser | None,
) -> str:
    # Determine the effective role using SCIM bindings, claim mappings, and defaults.
    role = None
    if user is not None:
        role = await resolve_role_from_scim(session=session, tenant_id=tenant_id, user_id=user.id)
    if role is None:
        role = resolve_role_from_claims(provider.role_mapping_json, claims)
    if role is None:
        role = provider.default_role
    return normalize_role(role)


async def ensure_tenant_user(
    *,
    session,
    tenant_id: str,
    claims: OidcClaims,
    role: str,
    jit_enabled: bool,
) -> tuple[TenantUser, bool]:
    # Create or update tenant users as part of the SSO flow.
    result = await session.execute(
        select(TenantUser).where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.external_subject == claims.subject,
        )
    )
    tenant_user = result.scalar_one_or_none()
    now = _utc_now()
    if tenant_user is None:
        if not jit_enabled:
            raise JitProvisioningDisabled()
        tenant_user = TenantUser(
            id=secrets.token_hex(16),
            tenant_id=tenant_id,
            external_subject=claims.subject,
            email=claims.email,
            display_name=claims.name,
            status="active",
            role=role,
            last_login_at=now,
        )
        session.add(tenant_user)
        return tenant_user, True
    if tenant_user.status != "active":
        raise TenantUserDisabled()
    tenant_user.email = claims.email or tenant_user.email
    tenant_user.display_name = claims.name or tenant_user.display_name
    tenant_user.last_login_at = now
    return tenant_user, False
