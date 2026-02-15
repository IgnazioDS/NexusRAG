from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, get_optional_principal
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import IdentityProvider, TenantUser
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.auth.api_keys import normalize_role
from nexusrag.services.auth.oidc import (
    JitProvisioningDisabled,
    TenantUserDisabled,
    append_query_params,
    build_authorize_url,
    build_code_challenge,
    exchange_code_for_tokens,
    ensure_tenant_user,
    extract_claims,
    generate_nonce,
    generate_pkce_verifier,
    generate_state,
    pop_nonce,
    pop_state,
    resolve_role,
    store_nonce,
    store_state,
    validate_id_token,
)
from nexusrag.services.auth.sso_sessions import create_sso_session
from nexusrag.services.entitlements import (
    FEATURE_IDENTITY_JIT,
    FEATURE_IDENTITY_SSO,
    require_feature,
)


router = APIRouter(prefix="/auth/sso", tags=["sso"], responses=DEFAULT_ERROR_RESPONSES)


class SsoProviderSummary(BaseModel):
    id: str
    name: str
    type: str
    issuer: str
    auth_url: str
    scopes: list[str] | None
    jit_enabled: bool


class SsoProviderList(BaseModel):
    items: list[SsoProviderSummary]


class SsoLoginResponse(BaseModel):
    tenant_id: str
    provider_id: str
    user_id: str
    role: str
    session_token: str
    expires_at: str | None


class SsoStartResponse(BaseModel):
    authorize_url: str


def _utc_now() -> datetime:
    # Keep SSO timestamps in UTC for uniform audit records.
    return datetime.now(timezone.utc)


def _sso_disabled() -> HTTPException:
    # Gate SSO when globally disabled.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "IDENTITY_FEATURE_DISABLED", "message": "SSO is disabled"},
    )


def _provider_not_found() -> HTTPException:
    # Return a stable error when IdPs are missing.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "SSO_PROVIDER_NOT_FOUND", "message": "SSO provider not found"},
    )


def _invalid_state() -> HTTPException:
    # Fail closed when state or nonce validation fails.
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "SSO_INVALID_STATE", "message": "Invalid or expired state"},
    )


def _token_exchange_failed() -> HTTPException:
    # Surface upstream IdP failures with a stable error code.
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": "SSO_TOKEN_EXCHANGE_FAILED", "message": "Token exchange failed"},
    )


def _id_token_invalid() -> HTTPException:
    # Return 401 for invalid ID tokens.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "SSO_ID_TOKEN_INVALID", "message": "ID token invalid"},
    )


def _jit_disabled() -> HTTPException:
    # Prevent provisioning when JIT is disabled.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "SSO_JIT_DISABLED", "message": "JIT provisioning disabled"},
    )


def _validate_return_to(return_to: str, settings) -> None:
    # Enforce allowed redirect hosts and HTTPS requirements outside dev.
    parsed = urlparse(return_to)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "BAD_REQUEST", "message": "Invalid redirect URI"},
        )
    if not settings.auth_dev_bypass and parsed.scheme != "https":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "BAD_REQUEST", "message": "HTTPS redirect URIs are required"},
        )
    allowed_hosts = [host.strip() for host in settings.sso_allowed_redirect_hosts.split(",") if host.strip()]
    if allowed_hosts and parsed.hostname not in allowed_hosts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "BAD_REQUEST", "message": "Redirect host not allowed"},
        )


def _callback_url(request: Request, provider_id: str) -> str:
    # Build the callback URL from the incoming request context.
    return str(request.url_for("oidc_callback", provider_id=provider_id))


@router.get(
    "/providers",
    response_model=SuccessEnvelope[SsoProviderList] | SsoProviderList,
)
async def list_sso_providers(
    request: Request,
    tenant_id: str | None = Query(default=None),
    principal: Principal | None = Depends(get_optional_principal),
    db: AsyncSession = Depends(get_db),
) -> SsoProviderList:
    # List enabled providers for admins or public discovery when configured.
    settings = get_settings()
    if not settings.sso_enabled:
        raise _sso_disabled()

    resolved_tenant = principal.tenant_id if principal else tenant_id
    if resolved_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_UNAUTHORIZED", "message": "Tenant discovery requires authentication"},
        )
    if principal and principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "AUTH_FORBIDDEN", "message": "Admin role required"},
        )
    if principal is None and not settings.sso_public_discovery_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "AUTH_FORBIDDEN", "message": "Public discovery disabled"},
        )

    await require_feature(session=db, tenant_id=resolved_tenant, feature_key=FEATURE_IDENTITY_SSO)

    result = await db.execute(
        select(IdentityProvider)
        .where(IdentityProvider.tenant_id == resolved_tenant, IdentityProvider.enabled.is_(True))
        .order_by(IdentityProvider.name)
    )
    providers = result.scalars().all()
    payload = SsoProviderList(
        items=[
            SsoProviderSummary(
                id=provider.id,
                name=provider.name,
                type=provider.type,
                issuer=provider.issuer,
                auth_url=provider.auth_url,
                scopes=provider.scopes_json,
                jit_enabled=provider.jit_enabled,
            )
            for provider in providers
        ]
    )
    return success_response(request=request, data=payload)


@router.get(
    "/oidc/{provider_id}/start",
    response_model=SuccessEnvelope[SsoStartResponse] | SsoStartResponse,
)
async def oidc_start(
    request: Request,
    provider_id: str,
    return_to: str | None = Query(default=None),
    response_mode: Literal["json", "redirect"] = Query(default="json"),
    db: AsyncSession = Depends(get_db),
) -> SsoStartResponse:
    # Initiate an OIDC flow with state, nonce, and PKCE handling.
    settings = get_settings()
    if not settings.sso_enabled:
        raise _sso_disabled()

    provider = await db.get(IdentityProvider, provider_id)
    if provider is None or not provider.enabled or provider.type != "oidc":
        raise _provider_not_found()

    await require_feature(session=db, tenant_id=provider.tenant_id, feature_key=FEATURE_IDENTITY_SSO)

    if return_to:
        _validate_return_to(return_to, settings)

    redirect_uri = _callback_url(request, provider_id)
    if not settings.auth_dev_bypass and not redirect_uri.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "BAD_REQUEST", "message": "HTTPS callback URLs are required"},
        )

    state = generate_state()
    nonce = generate_nonce()
    pkce_verifier = generate_pkce_verifier()
    code_challenge = build_code_challenge(pkce_verifier)

    await store_state(
        state=state,
        payload={
            "tenant_id": provider.tenant_id,
            "provider_id": provider.id,
            "nonce": nonce,
            "pkce_verifier": pkce_verifier,
            "redirect_uri": redirect_uri,
            "return_to": return_to,
            "response_mode": response_mode,
        },
        ttl_seconds=settings.sso_state_ttl_seconds,
    )
    await store_nonce(nonce=nonce, ttl_seconds=settings.sso_nonce_ttl_seconds)

    authorize_url = build_authorize_url(
        provider=provider,
        redirect_uri=redirect_uri,
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
    )
    if response_mode == "redirect":
        return RedirectResponse(authorize_url)
    return success_response(request=request, data=SsoStartResponse(authorize_url=authorize_url))


@router.get(
    "/oidc/{provider_id}/callback",
    response_model=SuccessEnvelope[SsoLoginResponse] | SsoLoginResponse,
    name="oidc_callback",
)
async def oidc_callback(
    request: Request,
    provider_id: str,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[SsoLoginResponse] | SsoLoginResponse | RedirectResponse:
    # Handle OIDC callbacks, validate tokens, and issue session tokens.
    settings = get_settings()
    if not settings.sso_enabled:
        raise _sso_disabled()

    provider = await db.get(IdentityProvider, provider_id)
    if provider is None or not provider.enabled or provider.type != "oidc":
        raise _provider_not_found()

    # Cache provider fields to avoid async lazy-load after rollbacks/commits.
    provider_id_value = provider.id
    provider_tenant_id = provider.tenant_id
    request_ctx = get_request_context(request)

    try:
        state_payload = await pop_state(state)
        if not state_payload or state_payload.get("provider_id") != provider_id:
            raise _invalid_state()
        if not await pop_nonce(state_payload.get("nonce")):
            raise _invalid_state()

        await require_feature(
            session=db, tenant_id=provider_tenant_id, feature_key=FEATURE_IDENTITY_SSO
        )
    except HTTPException as exc:
        await record_event(
            session=db,
            tenant_id=None,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="identity.sso.login.failure",
            outcome="failure",
            resource_type="identity_provider",
            resource_id=provider_id_value,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={"reason": "state_or_entitlement_invalid"},
            error_code=exc.detail.get("code") if isinstance(exc.detail, dict) else None,
            commit=True,
            best_effort=True,
        )
        raise

    try:
        token_response = await exchange_code_for_tokens(
            provider=provider,
            code=code,
            redirect_uri=state_payload.get("redirect_uri"),
            code_verifier=state_payload.get("pkce_verifier"),
        )
    except Exception as exc:
        await record_event(
            session=db,
            tenant_id=None,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="identity.sso.login.failure",
            outcome="failure",
            resource_type="identity_provider",
            resource_id=provider_id_value,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={"reason": "token_exchange_failed"},
            error_code="SSO_TOKEN_EXCHANGE_FAILED",
            commit=True,
            best_effort=True,
        )
        raise _token_exchange_failed() from exc

    try:
        claims_payload = await validate_id_token(
            provider=provider,
            token=token_response.id_token,
            nonce=state_payload.get("nonce"),
            clock_skew_seconds=settings.sso_clock_skew_seconds,
        )
        claims = extract_claims(claims_payload)
    except Exception as exc:
        await record_event(
            session=db,
            tenant_id=None,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="identity.sso.login.failure",
            outcome="failure",
            resource_type="identity_provider",
            resource_id=provider_id_value,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={"reason": "id_token_invalid"},
            error_code="SSO_ID_TOKEN_INVALID",
            commit=True,
            best_effort=True,
        )
        raise _id_token_invalid() from exc

    try:
        existing_user = (
            await db.execute(
                select(TenantUser).where(
                    TenantUser.tenant_id == provider_tenant_id,
                    TenantUser.external_subject == claims.subject,
                )
            )
        ).scalar_one_or_none()
        role = await resolve_role(
            session=db,
            provider=provider,
            claims=claims,
            tenant_id=provider_tenant_id,
            user=existing_user,
        )
        if existing_user is None and provider.jit_enabled:
            await require_feature(
                session=db, tenant_id=provider_tenant_id, feature_key=FEATURE_IDENTITY_JIT
            )
        tenant_user, created = await ensure_tenant_user(
            session=db,
            tenant_id=provider_tenant_id,
            claims=claims,
            role=role,
            jit_enabled=provider.jit_enabled,
        )
        # Flush to ensure the tenant user exists before creating the session row.
        await db.flush()
        if normalize_role(tenant_user.role) != role:
            tenant_user.role = role
            await record_event(
                session=db,
                tenant_id=tenant_user.tenant_id,
                actor_type="system",
                actor_id=provider_id_value,
                actor_role=None,
                event_type="identity.role.changed",
                outcome="success",
                resource_type="tenant_user",
                resource_id=tenant_user.id,
                metadata={"source": "sso", "role": role},
                commit=False,
                best_effort=True,
            )

        session_token, session_row = await create_sso_session(
            session=db,
            tenant_id=tenant_user.tenant_id,
            user_id=tenant_user.id,
            provider_id=provider_id_value,
            ttl_hours=settings.sso_session_ttl_hours,
        )
        await db.commit()
    except JitProvisioningDisabled:
        await db.rollback()
        await record_event(
            session=db,
            tenant_id=provider_tenant_id,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="identity.sso.login.failure",
            outcome="failure",
            resource_type="identity_provider",
            resource_id=provider_id_value,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={"reason": "jit_disabled"},
            error_code="SSO_JIT_DISABLED",
            commit=True,
            best_effort=True,
        )
        raise _jit_disabled()
    except TenantUserDisabled:
        await db.rollback()
        await record_event(
            session=db,
            tenant_id=provider_tenant_id,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="identity.sso.login.failure",
            outcome="failure",
            resource_type="identity_provider",
            resource_id=provider_id_value,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={"reason": "tenant_user_disabled"},
            error_code="AUTH_FORBIDDEN",
            commit=True,
            best_effort=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "AUTH_FORBIDDEN", "message": "Tenant user disabled"},
        )
    except HTTPException:
        await db.rollback()
        await record_event(
            session=db,
            tenant_id=provider_tenant_id,
            actor_type="anonymous",
            actor_id=None,
            actor_role=None,
            event_type="identity.sso.login.failure",
            outcome="failure",
            resource_type="identity_provider",
            resource_id=provider_id_value,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={"reason": "jit_or_user_blocked"},
            commit=True,
            best_effort=True,
        )
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        await record_event(
            session=db,
            tenant_id=provider_tenant_id,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type="identity.sso.login.failure",
            outcome="failure",
            resource_type="identity_provider",
            resource_id=provider_id_value,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={"reason": "db_error"},
            error_code="INTERNAL_ERROR",
            commit=True,
            best_effort=True,
        )
        raise HTTPException(status_code=500, detail="Database error") from exc

    if created:
        await record_event(
            session=db,
            tenant_id=tenant_user.tenant_id,
            actor_type="system",
            actor_id=provider_id_value,
            actor_role=None,
            event_type="identity.jit.user_created",
            outcome="success",
            resource_type="tenant_user",
            resource_id=tenant_user.id,
            request_id=request_ctx["request_id"],
            ip_address=request_ctx["ip_address"],
            user_agent=request_ctx["user_agent"],
            metadata={"provider_id": provider.id},
            commit=True,
            best_effort=True,
        )

    await record_event(
        session=db,
        tenant_id=tenant_user.tenant_id,
        actor_type="tenant_user",
        actor_id=tenant_user.id,
        actor_role=tenant_user.role,
        event_type="identity.sso.login.success",
        outcome="success",
        resource_type="sso_session",
        resource_id=session_row.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"provider_id": provider_id_value},
        commit=True,
        best_effort=True,
    )

    payload = SsoLoginResponse(
        tenant_id=tenant_user.tenant_id,
        provider_id=provider_id_value,
        user_id=tenant_user.id,
        role=tenant_user.role,
        session_token=session_token,
        expires_at=session_row.expires_at.isoformat() if session_row.expires_at else None,
    )

    return_to = state_payload.get("return_to") if state_payload else None
    response_mode = state_payload.get("response_mode") if state_payload else None
    if return_to and response_mode == "redirect":
        redirect_url = append_query_params(
            return_to,
            {
                "token": session_token,
                "tenant_id": tenant_user.tenant_id,
                "provider_id": provider_id_value,
            },
        )
        return RedirectResponse(redirect_url)

    return success_response(request=request, data=payload)
