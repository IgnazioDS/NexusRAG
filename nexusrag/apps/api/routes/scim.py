from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import get_db
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    ScimGroup,
    ScimGroupMembership,
    ScimIdentity,
    ScimToken,
    TenantUser,
)
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.auth.api_keys import normalize_role
from nexusrag.services.auth.scim import (
    ScimUserInput,
    SCIM_SCHEMA_PATCH,
    apply_active_status,
    apply_scim_group_patch,
    apply_scim_user_patch,
    build_scim_group_resource,
    build_scim_list_response,
    build_scim_service_provider_config,
    build_scim_user_resource,
    hash_scim_token,
    parse_scim_group_payload,
    parse_scim_user_payload,
    resolve_role_from_groups,
)
from nexusrag.services.entitlements import FEATURE_IDENTITY_SCIM, require_feature


router = APIRouter(prefix="/scim/v2", tags=["scim"], responses=DEFAULT_ERROR_RESPONSES)


class ScimPrincipal:
    # Represent SCIM bearer tokens for tenant-scoped provisioning.
    def __init__(self, tenant_id: str, token_id: str) -> None:
        self.tenant_id = tenant_id
        self.token_id = token_id


def _utc_now() -> datetime:
    # Use UTC timestamps for SCIM audit entries and metadata.
    return datetime.now(timezone.utc)


def _scim_unauthorized(message: str) -> HTTPException:
    # Return stable SCIM auth failures with 401 responses.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "SCIM_UNAUTHORIZED", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _scim_payload_invalid(message: str) -> HTTPException:
    # Return consistent SCIM payload validation errors.
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "SCIM_PAYLOAD_INVALID", "message": message},
    )


def _identity_disabled() -> HTTPException:
    # Gate SCIM when globally disabled.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "IDENTITY_FEATURE_DISABLED", "message": "SCIM is disabled"},
    )


def _parse_bearer_token(header_value: str | None) -> str | None:
    # Enforce bearer token formatting for SCIM auth.
    if not header_value:
        return None
    parts = header_value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _scim_unauthorized("Missing or invalid bearer token")
    return parts[1]


async def _require_scim_principal(
    request: Request,
    db: AsyncSession,
) -> ScimPrincipal:
    # Resolve SCIM bearer tokens and enforce entitlements.
    settings = get_settings()
    if not settings.scim_enabled:
        raise _identity_disabled()
    raw_token = _parse_bearer_token(request.headers.get("Authorization"))
    if not raw_token:
        raise _scim_unauthorized("Missing bearer token")
    token_hash = hash_scim_token(raw_token)
    result = await db.execute(select(ScimToken).where(ScimToken.token_hash == token_hash))
    token = result.scalar_one_or_none()
    if token is None or token.revoked_at is not None:
        raise _scim_unauthorized("Invalid SCIM token")
    if token.expires_at is not None and token.expires_at <= _utc_now():
        raise _scim_unauthorized("SCIM token expired")

    await require_feature(session=db, tenant_id=token.tenant_id, feature_key=FEATURE_IDENTITY_SCIM)

    await db.execute(
        update(ScimToken)
        .where(ScimToken.id == token.id)
        .values(last_used_at=_utc_now())
    )
    await db.commit()
    return ScimPrincipal(tenant_id=token.tenant_id, token_id=token.id)


async def _load_user_groups(
    db: AsyncSession,
    user_ids: list[str],
) -> dict[str, list[ScimGroup]]:
    # Load SCIM groups for a set of users in a single query.
    if not user_ids:
        return {}
    result = await db.execute(
        select(ScimGroup, ScimGroupMembership)
        .join(ScimGroupMembership, ScimGroupMembership.group_id == ScimGroup.id)
        .where(ScimGroupMembership.user_id.in_(user_ids))
    )
    mapping: dict[str, list[ScimGroup]] = {user_id: [] for user_id in user_ids}
    for group, membership in result.fetchall():
        mapping.setdefault(membership.user_id, []).append(group)
    return mapping


async def _sync_user_memberships(
    *,
    db: AsyncSession,
    user_id: str,
    group_ids: list[str],
    tenant_id: str,
) -> None:
    # Replace group memberships for a user using SCIM group identifiers.
    if group_ids:
        valid_rows = await db.execute(
            select(ScimGroup.id).where(
                ScimGroup.tenant_id == tenant_id,
                ScimGroup.id.in_(group_ids),
            )
        )
        desired = {row[0] for row in valid_rows.fetchall()}
    else:
        desired = set()
    result = await db.execute(
        select(ScimGroupMembership.group_id)
        .where(ScimGroupMembership.user_id == user_id)
    )
    existing = {row[0] for row in result.fetchall()}
    to_add = desired - existing
    to_remove = existing - desired
    if to_remove:
        await db.execute(
            ScimGroupMembership.__table__.delete().where(
                ScimGroupMembership.user_id == user_id,
                ScimGroupMembership.group_id.in_(to_remove),
            )
        )
    for group_id in to_add:
        db.add(ScimGroupMembership(group_id=group_id, user_id=user_id))


async def _sync_group_memberships_for_group(
    *,
    db: AsyncSession,
    group_id: str,
    user_ids: list[str],
    tenant_id: str,
) -> None:
    # Replace group memberships for a group using SCIM user identifiers.
    if user_ids:
        valid_rows = await db.execute(
            select(TenantUser.id).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.id.in_(user_ids),
            )
        )
        desired = {row[0] for row in valid_rows.fetchall()}
    else:
        desired = set()
    result = await db.execute(
        select(ScimGroupMembership.user_id)
        .where(ScimGroupMembership.group_id == group_id)
    )
    existing = {row[0] for row in result.fetchall()}
    to_add = desired - existing
    to_remove = existing - desired
    if to_remove:
        await db.execute(
            ScimGroupMembership.__table__.delete().where(
                ScimGroupMembership.group_id == group_id,
                ScimGroupMembership.user_id.in_(to_remove),
            )
        )
    for user_id in to_add:
        db.add(ScimGroupMembership(group_id=group_id, user_id=user_id))


async def _recompute_role_from_groups(
    *,
    db: AsyncSession,
    tenant_id: str,
    user: TenantUser,
) -> None:
    # Update tenant user roles based on SCIM group bindings when configured.
    groups_map = await _load_user_groups(db, [user.id])
    role = resolve_role_from_groups(groups_map.get(user.id, []))
    if role is None:
        return
    if normalize_role(user.role) != normalize_role(role):
        user.role = normalize_role(role)
        await record_event(
            session=db,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type="identity.role.changed",
            outcome="success",
            resource_type="tenant_user",
            resource_id=user.id,
            metadata={"source": "scim", "role": user.role},
            commit=False,
            best_effort=True,
        )


@router.get(
    "/ServiceProviderConfig",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def service_provider_config(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Return SCIM ServiceProviderConfig metadata for provisioning clients.
    await _require_scim_principal(request, db)
    payload = build_scim_service_provider_config()
    return success_response(request=request, data=payload)


@router.get(
    "/Users",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def list_users(
    request: Request,
    startIndex: int = Query(default=1, ge=1),
    count: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # List SCIM users with pagination support.
    principal = await _require_scim_principal(request, db)
    settings = get_settings()
    resolved_count = count or settings.scim_default_page_size
    resolved_count = min(resolved_count, settings.scim_max_page_size)
    offset = startIndex - 1

    total = await db.scalar(
        select(func.count()).select_from(TenantUser).where(TenantUser.tenant_id == principal.tenant_id)
    )
    result = await db.execute(
        select(TenantUser)
        .where(TenantUser.tenant_id == principal.tenant_id)
        .order_by(TenantUser.created_at.asc())
        .offset(offset)
        .limit(resolved_count)
    )
    users = list(result.scalars().all())
    identities = {}
    if users:
        identity_rows = await db.execute(
            select(ScimIdentity).where(ScimIdentity.user_id.in_([user.id for user in users]))
        )
        identities = {row.user_id: row for row in identity_rows.scalars().all()}
    groups_map = await _load_user_groups(db, [user.id for user in users])

    resources = [
        build_scim_user_resource(
            user=user,
            identity=identities.get(user.id),
            groups=groups_map.get(user.id, []),
        )
        for user in users
    ]
    payload = build_scim_list_response(
        resources=resources,
        total_results=int(total or 0),
        start_index=startIndex,
        items_per_page=resolved_count,
    )
    return success_response(request=request, data=payload)


@router.post(
    "/Users",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    request: Request,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Create or update a SCIM user entry with idempotent semantics.
    principal = await _require_scim_principal(request, db)
    parsed = parse_scim_user_payload(payload)
    if not parsed.user_name:
        raise _scim_payload_invalid("userName is required")

    external_subject = parsed.external_id or parsed.user_name
    now = _utc_now()
    tenant_user: TenantUser | None = None
    scim_identity: ScimIdentity | None = None

    if parsed.external_id:
        result = await db.execute(
            select(ScimIdentity).where(
                ScimIdentity.tenant_id == principal.tenant_id,
                ScimIdentity.external_id == parsed.external_id,
            )
        )
        scim_identity = result.scalar_one_or_none()
        if scim_identity:
            tenant_user = await db.get(TenantUser, scim_identity.user_id)

    if tenant_user is None:
        result = await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == principal.tenant_id,
                TenantUser.external_subject == external_subject,
            )
        )
        tenant_user = result.scalar_one_or_none()

    created = tenant_user is None
    if tenant_user is None:
        tenant_user = TenantUser(
            id=uuid4().hex,
            tenant_id=principal.tenant_id,
            external_subject=external_subject,
            email=parsed.email,
            display_name=parsed.display_name,
            status=apply_active_status(parsed.active) or "active",
            role="reader",
            last_login_at=None,
        )
        db.add(tenant_user)
        await db.flush()

    tenant_user.email = parsed.email or tenant_user.email
    tenant_user.display_name = parsed.display_name or tenant_user.display_name
    if parsed.active is not None:
        tenant_user.status = apply_active_status(parsed.active) or tenant_user.status

    if scim_identity is None:
        scim_identity = ScimIdentity(
            id=uuid4().hex,
            tenant_id=principal.tenant_id,
            external_id=parsed.external_id or external_subject,
            user_id=tenant_user.id,
            provider_id=None,
            last_sync_at=now,
            active=tenant_user.status == "active",
        )
        db.add(scim_identity)
    else:
        scim_identity.external_id = parsed.external_id or scim_identity.external_id
        scim_identity.last_sync_at = now
        scim_identity.active = tenant_user.status == "active"

    if parsed.groups is not None:
        await _sync_user_memberships(
            db=db,
            user_id=tenant_user.id,
            group_ids=parsed.groups,
            tenant_id=principal.tenant_id,
        )
        await _recompute_role_from_groups(db=db, tenant_id=principal.tenant_id, user=tenant_user)

    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(tenant_user)
    if scim_identity is not None:
        await db.refresh(scim_identity)

    request_ctx = get_request_context(request)
    event_type = "identity.scim.user.created" if created else "identity.scim.user.updated"
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="scim",
        actor_id=principal.token_id,
        actor_role=None,
        event_type=event_type,
        outcome="success",
        resource_type="tenant_user",
        resource_id=tenant_user.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"active": tenant_user.status == "active"},
        commit=True,
        best_effort=True,
    )

    if tenant_user.status != "active":
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="scim",
            actor_id=principal.token_id,
            actor_role=None,
            event_type="identity.scim.user.disabled",
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

    groups_map = await _load_user_groups(db, [tenant_user.id])
    resource = build_scim_user_resource(
        user=tenant_user,
        identity=scim_identity,
        groups=groups_map.get(tenant_user.id, []),
    )
    return success_response(request=request, data=resource)


@router.get(
    "/Users/{user_id}",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def get_user(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Fetch a single SCIM user by resource id.
    principal = await _require_scim_principal(request, db)
    tenant_user = await db.get(TenantUser, user_id)
    if tenant_user is None or tenant_user.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})
    identity = (
        await db.execute(select(ScimIdentity).where(ScimIdentity.user_id == tenant_user.id))
    ).scalar_one_or_none()
    groups_map = await _load_user_groups(db, [tenant_user.id])
    resource = build_scim_user_resource(
        user=tenant_user,
        identity=identity,
        groups=groups_map.get(tenant_user.id, []),
    )
    return success_response(request=request, data=resource)


@router.patch(
    "/Users/{user_id}",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def patch_user(
    request: Request,
    user_id: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Apply SCIM PATCH operations for user updates.
    principal = await _require_scim_principal(request, db)
    if SCIM_SCHEMA_PATCH not in (payload.get("schemas") or []):
        raise _scim_payload_invalid("PATCH schema missing")

    tenant_user = await db.get(TenantUser, user_id)
    if tenant_user is None or tenant_user.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})

    identity = (
        await db.execute(select(ScimIdentity).where(ScimIdentity.user_id == tenant_user.id))
    ).scalar_one_or_none()
    groups_map = await _load_user_groups(db, [tenant_user.id])
    current = ScimUserInput(
        external_id=identity.external_id if identity else None,
        user_name=tenant_user.external_subject,
        email=tenant_user.email,
        display_name=tenant_user.display_name,
        active=tenant_user.status == "active",
        groups=[group.id for group in groups_map.get(tenant_user.id, [])],
    )

    updated = apply_scim_user_patch(payload=payload, current=current)
    if updated.user_name:
        tenant_user.external_subject = updated.external_id or updated.user_name
    if updated.email is not None:
        tenant_user.email = updated.email
    if updated.display_name is not None:
        tenant_user.display_name = updated.display_name
    if updated.active is not None:
        tenant_user.status = apply_active_status(updated.active) or tenant_user.status

    now = _utc_now()
    if identity is None:
        identity = ScimIdentity(
            id=uuid4().hex,
            tenant_id=principal.tenant_id,
            external_id=updated.external_id or tenant_user.external_subject,
            user_id=tenant_user.id,
            provider_id=None,
            last_sync_at=now,
            active=tenant_user.status == "active",
        )
        db.add(identity)
    else:
        if updated.external_id:
            identity.external_id = updated.external_id
        identity.last_sync_at = now
        identity.active = tenant_user.status == "active"

    if updated.groups is not None:
        await _sync_user_memberships(
            db=db,
            user_id=tenant_user.id,
            group_ids=updated.groups,
            tenant_id=principal.tenant_id,
        )
        await _recompute_role_from_groups(db=db, tenant_id=principal.tenant_id, user=tenant_user)

    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(tenant_user)
    if identity is not None:
        await db.refresh(identity)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="scim",
        actor_id=principal.token_id,
        actor_role=None,
        event_type="identity.scim.user.updated",
        outcome="success",
        resource_type="tenant_user",
        resource_id=tenant_user.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"active": tenant_user.status == "active"},
        commit=True,
        best_effort=True,
    )

    if tenant_user.status != "active":
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="scim",
            actor_id=principal.token_id,
            actor_role=None,
            event_type="identity.scim.user.disabled",
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

    groups_map = await _load_user_groups(db, [tenant_user.id])
    resource = build_scim_user_resource(
        user=tenant_user,
        identity=identity,
        groups=groups_map.get(tenant_user.id, []),
    )
    return success_response(request=request, data=resource)


@router.delete(
    "/Users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user(
    request: Request,
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    # Disable SCIM users instead of hard deleting by default.
    principal = await _require_scim_principal(request, db)
    tenant_user = await db.get(TenantUser, user_id)
    if tenant_user is None or tenant_user.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})

    identity = (
        await db.execute(select(ScimIdentity).where(ScimIdentity.user_id == tenant_user.id))
    ).scalar_one_or_none()
    tenant_user.status = "disabled"
    if identity:
        identity.active = False
        identity.last_sync_at = _utc_now()
    await db.commit()

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="scim",
        actor_id=principal.token_id,
        actor_role=None,
        event_type="identity.scim.user.deleted",
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


@router.get(
    "/Groups",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def list_groups(
    request: Request,
    startIndex: int = Query(default=1, ge=1),
    count: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # List SCIM groups with pagination.
    principal = await _require_scim_principal(request, db)
    settings = get_settings()
    resolved_count = count or settings.scim_default_page_size
    resolved_count = min(resolved_count, settings.scim_max_page_size)
    offset = startIndex - 1

    total = await db.scalar(
        select(func.count()).select_from(ScimGroup).where(ScimGroup.tenant_id == principal.tenant_id)
    )
    result = await db.execute(
        select(ScimGroup)
        .where(ScimGroup.tenant_id == principal.tenant_id)
        .order_by(ScimGroup.display_name.asc())
        .offset(offset)
        .limit(resolved_count)
    )
    groups = list(result.scalars().all())
    resources: list[dict[str, Any]] = []
    for group in groups:
        members = (
            await db.execute(
                select(TenantUser)
                .join(ScimGroupMembership, ScimGroupMembership.user_id == TenantUser.id)
                .where(ScimGroupMembership.group_id == group.id)
            )
        ).scalars().all()
        resources.append(build_scim_group_resource(group=group, members=list(members)))

    payload = build_scim_list_response(
        resources=resources,
        total_results=int(total or 0),
        start_index=startIndex,
        items_per_page=resolved_count,
    )
    return success_response(request=request, data=payload)


@router.post(
    "/Groups",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    request: Request,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Create a SCIM group and optional membership list.
    principal = await _require_scim_principal(request, db)
    display_name, external_id, members = parse_scim_group_payload(payload)
    if not display_name:
        raise _scim_payload_invalid("displayName is required")

    group = None
    if external_id:
        result = await db.execute(
            select(ScimGroup).where(
                ScimGroup.tenant_id == principal.tenant_id,
                ScimGroup.external_id == external_id,
            )
        )
        group = result.scalar_one_or_none()

    if group is None:
        group = ScimGroup(
            id=uuid4().hex,
            tenant_id=principal.tenant_id,
            external_id=external_id or uuid4().hex,
            display_name=display_name,
            role_binding=None,
        )
        db.add(group)
    else:
        group.display_name = display_name

    if members is not None:
        await _sync_group_memberships_for_group(
            db=db,
            group_id=group.id,
            user_ids=members,
            tenant_id=principal.tenant_id,
        )
        for user_id in members:
            user = await db.get(TenantUser, user_id)
            if user and user.tenant_id == principal.tenant_id:
                await _recompute_role_from_groups(db=db, tenant_id=principal.tenant_id, user=user)

    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(group)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="scim",
        actor_id=principal.token_id,
        actor_role=None,
        event_type="identity.scim.group.updated",
        outcome="success",
        resource_type="scim_group",
        resource_id=group.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"display_name": group.display_name},
        commit=True,
        best_effort=True,
    )

    members_rows = (
        await db.execute(
            select(TenantUser)
            .join(ScimGroupMembership, ScimGroupMembership.user_id == TenantUser.id)
            .where(ScimGroupMembership.group_id == group.id)
        )
    ).scalars().all()
    resource = build_scim_group_resource(group=group, members=list(members_rows))
    return success_response(request=request, data=resource)


@router.patch(
    "/Groups/{group_id}",
    response_model=SuccessEnvelope[dict[str, Any]] | dict[str, Any],
)
async def patch_group(
    request: Request,
    group_id: str,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Apply SCIM PATCH operations for groups.
    principal = await _require_scim_principal(request, db)
    if SCIM_SCHEMA_PATCH not in (payload.get("schemas") or []):
        raise _scim_payload_invalid("PATCH schema missing")

    group = await db.get(ScimGroup, group_id)
    if group is None or group.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Group not found"})

    member_rows = (
        await db.execute(
            select(ScimGroupMembership.user_id).where(ScimGroupMembership.group_id == group_id)
        )
    ).fetchall()
    current_members = [row[0] for row in member_rows]
    new_name, new_members = apply_scim_group_patch(
        payload=payload,
        current_members=current_members,
        current_name=group.display_name,
    )
    group.display_name = new_name

    if new_members is not None:
        await _sync_group_memberships_for_group(
            db=db,
            group_id=group.id,
            user_ids=new_members,
            tenant_id=principal.tenant_id,
        )
        affected = set(current_members) | set(new_members)
        for user_id in affected:
            user = await db.get(TenantUser, user_id)
            if user and user.tenant_id == principal.tenant_id:
                await _recompute_role_from_groups(db=db, tenant_id=principal.tenant_id, user=user)

    await db.commit()
    # Refresh to avoid expired ORM attributes after commit when building responses.
    await db.refresh(group)

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="scim",
        actor_id=principal.token_id,
        actor_role=None,
        event_type="identity.scim.group.updated",
        outcome="success",
        resource_type="scim_group",
        resource_id=group.id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"display_name": group.display_name},
        commit=True,
        best_effort=True,
    )

    members_rows = (
        await db.execute(
            select(TenantUser)
            .join(ScimGroupMembership, ScimGroupMembership.user_id == TenantUser.id)
            .where(ScimGroupMembership.group_id == group.id)
        )
    ).scalars().all()
    resource = build_scim_group_resource(group=group, members=list(members_rows))
    return success_response(request=request, data=resource)


@router.delete(
    "/Groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_group(
    request: Request,
    group_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    # Delete SCIM groups and their memberships.
    principal = await _require_scim_principal(request, db)
    group = await db.get(ScimGroup, group_id)
    if group is None or group.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Group not found"})

    member_rows = (
        await db.execute(
            select(ScimGroupMembership.user_id).where(ScimGroupMembership.group_id == group_id)
        )
    ).fetchall()
    affected_users = [row[0] for row in member_rows]

    await db.execute(ScimGroupMembership.__table__.delete().where(ScimGroupMembership.group_id == group_id))
    await db.execute(ScimGroup.__table__.delete().where(ScimGroup.id == group_id))
    await db.commit()

    for user_id in affected_users:
        user = await db.get(TenantUser, user_id)
        if user and user.tenant_id == principal.tenant_id:
            await _recompute_role_from_groups(db=db, tenant_id=principal.tenant_id, user=user)
    await db.commit()

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="scim",
        actor_id=principal.token_id,
        actor_role=None,
        event_type="identity.scim.group.updated",
        outcome="success",
        resource_type="scim_group",
        resource_id=group_id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"deleted": True},
        commit=True,
        best_effort=True,
    )
