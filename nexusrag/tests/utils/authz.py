from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import DocumentPermission


def _permission_row(
    *,
    tenant_id: str,
    document_id: str,
    principal_type: str,
    principal_id: str,
    permission: str,
    granted_by: str | None,
    expires_at: datetime | None = None,
) -> DocumentPermission:
    # Build document permission rows for test fixtures.
    return DocumentPermission(
        id=uuid4().hex,
        tenant_id=tenant_id,
        document_id=document_id,
        principal_type=principal_type,
        principal_id=principal_id,
        permission=permission,
        granted_by=granted_by,
        expires_at=expires_at,
    )


async def grant_document_permission(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: str,
    principal_type: str,
    principal_id: str,
    permission: str,
    granted_by: str | None,
    expires_at: datetime | None = None,
) -> None:
    # Persist a single document permission for ACL tests.
    session.add(
        _permission_row(
            tenant_id=tenant_id,
            document_id=document_id,
            principal_type=principal_type,
            principal_id=principal_id,
            permission=permission,
            granted_by=granted_by,
            expires_at=expires_at,
        )
    )


async def grant_document_permissions(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_ids: list[str],
    principal_type: str,
    principal_id: str,
    permission: str,
    granted_by: str | None,
    expires_at: datetime | None = None,
) -> None:
    # Persist document permissions for multiple documents in tests.
    for document_id in document_ids:
        await grant_document_permission(
            session=session,
            tenant_id=tenant_id,
            document_id=document_id,
            principal_type=principal_type,
            principal_id=principal_id,
            permission=permission,
            granted_by=granted_by,
            expires_at=expires_at,
        )
