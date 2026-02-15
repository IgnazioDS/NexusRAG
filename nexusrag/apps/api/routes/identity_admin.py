from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import IdentityProvider, ScimToken, TenantUser
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.auth.api_keys import ROLE_ORDER, normalize_role
from nexusrag.services.auth.scim import compute_token_expiry, generate_scim_token
from nexusrag.services.entitlements import FEATURE_IDENTITY_SCIM, FEATURE_IDENTITY_SSO, require_feature


router = APIRouter(prefix="/admin/identity", tags=["identity"], responses=DEFAULT_ERROR_RESPONSES)


class IdentityProviderCreateRequest(BaseModel):
    type: Literal["oidc", "saml"]
    name: str = Field(min_length=1, max_length=128)
    issuer: str
    client_id: str
    client_secret_ref: str
    auth_url: str
    token_url: str
    jwks_url: str
    scopes_json: list[str] | None = None
    default_role: Literal["reader", "editor", "admin"]
    role_mapping_json: dict[str, Any] | None = None
    jit_enabled: bool = False


class IdentityProviderPatchRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    issuer: str | None = None
    client_id: str | None = None
    client_secret_ref: str | None = None
    auth_url: str | None = None
    token_url: str | None = None
    jwks_url: str | None = None
    scopes_json: list[str] | None = None
    default_role: Literal["reader", "editor", "admin"] | None = None
    role_mapping_json: dict[str, Any] | None = None
    jit_enabled: bool | None = None


class IdentityProviderResponse(BaseModel):
    id: str
    tenant_id: str
    type: str
    name: str
    issuer: str
    client_id: str
    client_secret_ref: str
    auth_url: str
    token_url: str
    jwks_url: str
    scopes_json: list[str] | None
    enabled: bool
    default_role: str
    role_mapping_json: dict[str, Any] | None
    jit_enabled: bool
    created_at: str | None
    updated_at: str | None


class IdentityProviderList(BaseModel):
    items: list[IdentityProviderResponse]


class IdentityProviderSecretRotateRequest(BaseModel):
    client_secret_ref: str


class ScimTokenCreateResponse(BaseModel):
    token_id: str
    token_prefix: str
    token: str
    expires_at: str | None


class ScimTokenRevokeRequest(BaseModel):
    token_id: str


class TenantUserResponse(BaseModel):
    id: str
    tenant_id: str
    external_subject: str
    email: str | None
    display_name: str | None
    status: str
    role: str
    last_login_at: str | None
    created_at: str | None
    updated_at: str | None


class TenantUserList(BaseModel):
    items: list[TenantUserResponse]


class TenantUserRolePatch(BaseModel):
    role: Literal["reader", "editor", "admin"]


class TenantUserActionResponse(BaseModel):
    id: str
    status: str
    role: str


def _utc_now() -> datetime:
    # Normalize identity timestamps to UTC for audit trails.
    return datetime.now(timezone.utc)


def _provider_payload(provider: IdentityProvider) -> IdentityProviderResponse:
    # Serialize identity providers for admin responses.
    return IdentityProviderResponse(
        id=provider.id,
        tenant_id=provider.tenant_id,
        type=provider.type,
        name=provider.name,
        issuer=provider.issuer,
        client_id=provider.client_id,
        client_secret_ref=provider.client_secret_ref,
        auth_url=provider.auth_url,
        token_url=provider.token_url,
        jwks_url=provider.jwks_url,
        scopes_json=provider.scopes_json,
        enabled=provider.enabled,
        default_role=provider.default_role,
        role_mapping_json=provider.role_mapping_json,
        jit_enabled=provider.jit_enabled,
        created_at=provider.created_at.isoformat() if provider.created_at else None,
        updated_at=provider.updated_at.isoformat() if provider.updated_at else None,
    )


def _user_payload(user: TenantUser) -> TenantUserResponse:
    # Serialize tenant users for admin inspection.
    return TenantUserResponse(
        id=user.id,
        tenant_id=user.tenant_id,
        external_subject=user.external_subject,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        role=user.role,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


def _validate_role_mapping(role_mapping: dict[str, Any] | None) -> None:
    # Validate role mapping payloads to avoid invalid RBAC assignments.
    if role_mapping is None:
        return
    if isinstance(role_mapping, dict) and "mapping" in role_mapping:
        mapping_values = role_mapping.get("mapping") or {}
        for role in mapping_values.values():
            _normalize_role_or_error(str(role))
        return
    if isinstance(role_mapping, dict):
        for mapping_values in role_mapping.values():
            if not isinstance(mapping_values, dict):
                continue
            for role in mapping_values.values():
                _normalize_role_or_error(str(role))


def _normalize_role_or_error(role: str) -> str:
    # Normalize roles while returning a consistent 400 error on invalid values.
    try:
        return normalize_role(role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTH_INVALID_ROLE", "message": str(exc)},
        ) from exc


def _require_sso_enabled(settings) -> None:
    # Gate identity admin endpoints when SSO is globally disabled.
    if not settings.sso_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "IDENTITY_FEATURE_DISABLED", "message": "SSO is disabled"},
        )


def _require_scim_enabled(settings) -> None:
    # Gate SCIM admin endpoints when provisioning is globally disabled.
    if not settings.scim_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "IDENTITY_FEATURE_DISABLED", "message": "SCIM is disabled"},
        )


@router.get(
    "/providers",
    response_model=SuccessEnvelope[IdentityProviderList] | IdentityProviderList,
)
async def list_providers(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> IdentityProviderList:
    # List tenant identity providers for admin management.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    rows = (
        await db.execute(
            select(IdentityProvider)
            .where(IdentityProvider.tenant_id == principal.tenant_id)
            .order_by(IdentityProvider.created_at.desc())
        )
    ).scalars().all()
    payload = IdentityProviderList(items=[_provider_payload(provider) for provider in rows])
    return success_response(request=request, data=payload)


@router.post(
    "/providers",
    response_model=SuccessEnvelope[IdentityProviderResponse] | IdentityProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    request: Request,
    payload: IdentityProviderCreateRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> IdentityProviderResponse:
    # Create identity providers with validated role defaults.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    default_role = _normalize_role_or_error(payload.default_role)
    _validate_role_mapping(payload.role_mapping_json)
    provider = IdentityProvider(
        id=uuid4().hex,
        tenant_id=principal.tenant_id,
        type=payload.type,
        name=payload.name,
        issuer=payload.issuer,
        client_id=payload.client_id,
        client_secret_ref=payload.client_secret_ref,
        auth_url=payload.auth_url,
        token_url=payload.token_url,
        jwks_url=payload.jwks_url,
        scopes_json=payload.scopes_json,
        enabled=False,
        default_role=default_role,
        role_mapping_json=payload.role_mapping_json,
        jit_enabled=payload.jit_enabled,
    )
    db.add(provider)
    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(provider)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.provider.created",
        outcome="success",
        resource_type="identity_provider",
        resource_id=provider.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"type": provider.type, "name": provider.name},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_provider_payload(provider))


@router.patch(
    "/providers/{provider_id}",
    response_model=SuccessEnvelope[IdentityProviderResponse] | IdentityProviderResponse,
)
async def patch_provider(
    request: Request,
    provider_id: str,
    payload: IdentityProviderPatchRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> IdentityProviderResponse:
    # Patch identity provider settings while preserving tenant scoping.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    provider = await db.get(IdentityProvider, provider_id)
    if provider is None or provider.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Provider not found"})

    updates = payload.model_dump(exclude_unset=True)
    if "default_role" in updates and updates["default_role"] is not None:
        updates["default_role"] = _normalize_role_or_error(updates["default_role"])
    if "role_mapping_json" in updates:
        _validate_role_mapping(updates.get("role_mapping_json"))
    for key, value in updates.items():
        setattr(provider, key, value)

    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(provider)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.provider.updated",
        outcome="success",
        resource_type="identity_provider",
        resource_id=provider.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"updated_fields": list(updates.keys())},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_provider_payload(provider))


@router.post(
    "/providers/{provider_id}/rotate-secret-ref",
    response_model=SuccessEnvelope[IdentityProviderResponse] | IdentityProviderResponse,
)
async def rotate_secret_ref(
    request: Request,
    provider_id: str,
    payload: IdentityProviderSecretRotateRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> IdentityProviderResponse:
    # Rotate client secret references without exposing plaintext values.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    provider = await db.get(IdentityProvider, provider_id)
    if provider is None or provider.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Provider not found"})
    provider.client_secret_ref = payload.client_secret_ref
    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(provider)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.provider.updated",
        outcome="success",
        resource_type="identity_provider",
        resource_id=provider.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"rotated_secret": True},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_provider_payload(provider))


@router.post(
    "/providers/{provider_id}/enable",
    response_model=SuccessEnvelope[IdentityProviderResponse] | IdentityProviderResponse,
)
async def enable_provider(
    request: Request,
    provider_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> IdentityProviderResponse:
    # Enable identity providers for active SSO use.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    provider = await db.get(IdentityProvider, provider_id)
    if provider is None or provider.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Provider not found"})
    provider.enabled = True
    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(provider)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.provider.enabled",
        outcome="success",
        resource_type="identity_provider",
        resource_id=provider.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata=None,
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_provider_payload(provider))


@router.post(
    "/providers/{provider_id}/disable",
    response_model=SuccessEnvelope[IdentityProviderResponse] | IdentityProviderResponse,
)
async def disable_provider(
    request: Request,
    provider_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> IdentityProviderResponse:
    # Disable identity providers without deleting configuration.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    provider = await db.get(IdentityProvider, provider_id)
    if provider is None or provider.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Provider not found"})
    provider.enabled = False
    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(provider)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.provider.disabled",
        outcome="success",
        resource_type="identity_provider",
        resource_id=provider.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata=None,
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_provider_payload(provider))


@router.post(
    "/scim/token/create",
    response_model=SuccessEnvelope[ScimTokenCreateResponse] | ScimTokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_scim_token(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ScimTokenCreateResponse:
    # Create tenant-scoped SCIM tokens for provisioning clients.
    settings = get_settings()
    _require_scim_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SCIM)
    token_id, raw_token, token_prefix, token_hash = generate_scim_token()
    expires_at = compute_token_expiry(settings.scim_token_ttl_days)
    scim_token = ScimToken(
        id=token_id,
        tenant_id=principal.tenant_id,
        token_prefix=token_prefix,
        token_hash=token_hash,
        expires_at=expires_at,
        last_used_at=None,
        revoked_at=None,
    )
    db.add(scim_token)
    await db.commit()

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.scim.token.created",
        outcome="success",
        resource_type="scim_token",
        resource_id=scim_token.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"token_prefix": scim_token.token_prefix},
        commit=True,
        best_effort=True,
    )

    response = ScimTokenCreateResponse(
        token_id=scim_token.id,
        token_prefix=scim_token.token_prefix,
        token=raw_token,
        expires_at=scim_token.expires_at.isoformat() if scim_token.expires_at else None,
    )
    return success_response(request=request, data=response)


@router.post(
    "/scim/token/revoke",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def revoke_scim_token(
    request: Request,
    payload: ScimTokenRevokeRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Revoke SCIM tokens to stop provisioning access.
    settings = get_settings()
    _require_scim_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SCIM)
    token = await db.get(ScimToken, payload.token_id)
    if token is None or token.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Token not found"})
    token.revoked_at = _utc_now()
    await db.commit()

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.scim.token.revoked",
        outcome="success",
        resource_type="scim_token",
        resource_id=token.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata=None,
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data={"revoked": True, "token_id": token.id})


@router.get(
    "/users",
    response_model=SuccessEnvelope[TenantUserList] | TenantUserList,
)
async def list_tenant_users(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> TenantUserList:
    # List tenant users managed via SSO and SCIM.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    rows = (
        await db.execute(
            select(TenantUser)
            .where(TenantUser.tenant_id == principal.tenant_id)
            .order_by(TenantUser.created_at.desc())
        )
    ).scalars().all()
    payload = TenantUserList(items=[_user_payload(user) for user in rows])
    return success_response(request=request, data=payload)


@router.patch(
    "/users/{user_id}/role",
    response_model=SuccessEnvelope[TenantUserActionResponse] | TenantUserActionResponse,
)
async def patch_user_role(
    request: Request,
    user_id: str,
    payload: TenantUserRolePatch,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> TenantUserActionResponse:
    # Change tenant user roles with optional escalation protections.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    tenant_user = await db.get(TenantUser, user_id)
    if tenant_user is None or tenant_user.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})

    settings = get_settings()
    new_role = _normalize_role_or_error(payload.role)
    current_role = _normalize_role_or_error(tenant_user.role)
    if settings.identity_dual_control_required and ROLE_ORDER[new_role] > ROLE_ORDER[current_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "AUTH_FORBIDDEN",
                "message": "Role escalation requires dual-control approval",
            },
        )

    tenant_user.role = new_role
    await db.commit()

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.role.changed",
        outcome="success",
        resource_type="tenant_user",
        resource_id=tenant_user.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"role": new_role},
        commit=True,
        best_effort=True,
    )

    payload_out = TenantUserActionResponse(
        id=tenant_user.id,
        status=tenant_user.status,
        role=tenant_user.role,
    )
    return success_response(request=request, data=payload_out)


@router.post(
    "/users/{user_id}/disable",
    response_model=SuccessEnvelope[TenantUserActionResponse] | TenantUserActionResponse,
)
async def disable_user(
    request: Request,
    user_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> TenantUserActionResponse:
    # Disable tenant users without deleting historical records.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    tenant_user = await db.get(TenantUser, user_id)
    if tenant_user is None or tenant_user.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})
    tenant_user.status = "disabled"
    await db.commit()

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.user.disabled",
        outcome="success",
        resource_type="tenant_user",
        resource_id=tenant_user.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata=None,
        commit=True,
        best_effort=True,
    )

    payload_out = TenantUserActionResponse(
        id=tenant_user.id,
        status=tenant_user.status,
        role=tenant_user.role,
    )
    return success_response(request=request, data=payload_out)


@router.post(
    "/users/{user_id}/enable",
    response_model=SuccessEnvelope[TenantUserActionResponse] | TenantUserActionResponse,
)
async def enable_user(
    request: Request,
    user_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> TenantUserActionResponse:
    # Enable disabled tenant users.
    settings = get_settings()
    _require_sso_enabled(settings)
    await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_IDENTITY_SSO)
    tenant_user = await db.get(TenantUser, user_id)
    if tenant_user is None or tenant_user.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})
    tenant_user.status = "active"
    await db.commit()

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="identity.user.enabled",
        outcome="success",
        resource_type="tenant_user",
        resource_id=tenant_user.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata=None,
        commit=True,
        best_effort=True,
    )

    payload_out = TenantUserActionResponse(
        id=tenant_user.id,
        status=tenant_user.status,
        role=tenant_user.role,
    )
    return success_response(request=request, data=payload_out)
