from __future__ import annotations

import pytest
from sqlalchemy import delete

from nexusrag.persistence.db import SessionLocal
from nexusrag.domain.models import TenantUser
from nexusrag.services.auth.oidc import JitProvisioningDisabled, OidcClaims, ensure_tenant_user


@pytest.mark.asyncio
async def test_jit_provisioning_creates_user() -> None:
    # Provision a tenant user when JIT is enabled.
    claims = OidcClaims(
        subject="sub-1",
        email="user@example.com",
        name="User One",
        groups=[],
        raw={},
    )
    async with SessionLocal() as session:
        user, created = await ensure_tenant_user(
            session=session,
            tenant_id="tenant-jit",
            claims=claims,
            role="reader",
            jit_enabled=True,
        )
        await session.commit()
        await session.execute(delete(TenantUser).where(TenantUser.tenant_id == "tenant-jit"))
        await session.commit()
    assert created is True
    assert user.external_subject == "sub-1"


@pytest.mark.asyncio
async def test_jit_provisioning_disabled_raises() -> None:
    # Raise when JIT provisioning is disabled and no user exists.
    claims = OidcClaims(
        subject="sub-2",
        email="user2@example.com",
        name="User Two",
        groups=[],
        raw={},
    )
    async with SessionLocal() as session:
        with pytest.raises(JitProvisioningDisabled):
            await ensure_tenant_user(
                session=session,
                tenant_id="tenant-nojit",
                claims=claims,
                role="reader",
                jit_enabled=False,
            )
        await session.execute(delete(TenantUser).where(TenantUser.tenant_id == "tenant-nojit"))
        await session.commit()
