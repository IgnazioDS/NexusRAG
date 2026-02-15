from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import (
    AuthorizationPolicy,
    DocumentLabel,
    DocumentPermission,
    PrincipalAttribute,
)
from nexusrag.persistence.guards import require_tenant_id, tenant_predicate


async def list_policies(
    session: AsyncSession,
    *,
    tenant_id: str,
    include_global: bool = False,
    include_disabled: bool = True,
) -> list[AuthorizationPolicy]:
    # Use tenant predicates to guarantee scoping while optionally including global templates.
    require_tenant_id(tenant_id)
    predicate = tenant_predicate(AuthorizationPolicy, tenant_id)
    if include_global:
        predicate = or_(predicate, AuthorizationPolicy.tenant_id.is_(None))
    stmt = select(AuthorizationPolicy).where(predicate)
    if not include_disabled:
        stmt = stmt.where(AuthorizationPolicy.enabled.is_(True))
    result = await session.execute(stmt.order_by(AuthorizationPolicy.priority.desc(), AuthorizationPolicy.id.asc()))
    return list(result.scalars().all())


async def get_policy(
    session: AsyncSession,
    *,
    tenant_id: str,
    policy_id: str,
    include_global: bool = False,
) -> AuthorizationPolicy | None:
    # Fetch a single policy while enforcing tenant scoping.
    require_tenant_id(tenant_id)
    predicate = tenant_predicate(AuthorizationPolicy, tenant_id)
    if include_global:
        predicate = or_(predicate, AuthorizationPolicy.tenant_id.is_(None))
    result = await session.execute(
        select(AuthorizationPolicy).where(and_(AuthorizationPolicy.id == policy_id, predicate))
    )
    return result.scalar_one_or_none()


async def list_document_permissions(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: str,
) -> list[DocumentPermission]:
    # Return explicit document permissions scoped to a tenant and document.
    require_tenant_id(tenant_id)
    result = await session.execute(
        select(DocumentPermission).where(
            tenant_predicate(DocumentPermission, tenant_id),
            DocumentPermission.document_id == document_id,
        )
    )
    return list(result.scalars().all())


async def delete_permission(
    session: AsyncSession,
    *,
    tenant_id: str,
    permission_id: str,
) -> DocumentPermission | None:
    # Delete a document permission row with tenant scoping.
    require_tenant_id(tenant_id)
    result = await session.execute(
        select(DocumentPermission).where(
            DocumentPermission.id == permission_id,
            tenant_predicate(DocumentPermission, tenant_id),
        )
    )
    permission = result.scalar_one_or_none()
    if permission is None:
        return None
    await session.execute(
        delete(DocumentPermission).where(
            DocumentPermission.id == permission_id,
            tenant_predicate(DocumentPermission, tenant_id),
        )
    )
    return permission


async def list_document_labels(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: str,
) -> list[DocumentLabel]:
    # Return ABAC labels for a document within the tenant boundary.
    require_tenant_id(tenant_id)
    result = await session.execute(
        select(DocumentLabel).where(
            tenant_predicate(DocumentLabel, tenant_id),
            DocumentLabel.document_id == document_id,
        )
    )
    return list(result.scalars().all())


async def get_principal_attributes(
    session: AsyncSession,
    *,
    tenant_id: str,
    principal_type: str,
    principal_id: str,
) -> PrincipalAttribute | None:
    # Fetch cached principal attributes for ABAC evaluation.
    require_tenant_id(tenant_id)
    result = await session.execute(
        select(PrincipalAttribute).where(
            tenant_predicate(PrincipalAttribute, tenant_id),
            PrincipalAttribute.principal_type == principal_type,
            PrincipalAttribute.principal_id == principal_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_principal_attributes(
    session: AsyncSession,
    *,
    tenant_id: str,
    principal_type: str,
    principal_id: str,
    attrs_json: dict,
    now: datetime,
) -> PrincipalAttribute:
    # Maintain a single cached attribute row for a given principal.
    require_tenant_id(tenant_id)
    existing = await get_principal_attributes(
        session,
        tenant_id=tenant_id,
        principal_type=principal_type,
        principal_id=principal_id,
    )
    if existing is None:
        row = PrincipalAttribute(
            id=uuid4().hex,
            tenant_id=tenant_id,
            principal_type=principal_type,
            principal_id=principal_id,
            attrs_json=attrs_json,
            updated_at=now,
        )
        session.add(row)
        return row
    existing.attrs_json = attrs_json
    existing.updated_at = now
    return existing
