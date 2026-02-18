from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import ApiKey, AuthorizationPolicy, TenantPlanAssignment, User
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.auth.api_keys import generate_api_key, normalize_role


def _utc_now() -> datetime:
    # Keep timestamps consistent for test-generated auth records.
    return datetime.now(timezone.utc)


async def create_test_api_key(
    *,
    tenant_id: str,
    role: str,
    name: str = "test-key",
    user_active: bool = True,
    key_revoked: bool = False,
    key_expires_at: datetime | None = None,
    plan_id: str | None = "enterprise",
    seed_authz_policies: bool = True,
) -> tuple[str, dict[str, str], str, str]:
    # Provision a user + API key pair for integration tests.
    normalized_role = normalize_role(role)
    user_id = uuid4().hex
    key_id, raw_key, key_prefix, key_hash = generate_api_key()

    async with SessionLocal() as session:
        user = User(
            id=user_id,
            tenant_id=tenant_id,
            email=None,
            role=normalized_role,
            is_active=user_active,
        )
        api_key = ApiKey(
            id=key_id,
            user_id=user.id,
            tenant_id=tenant_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            name=name,
            expires_at=key_expires_at,
            revoked_at=_utc_now() if key_revoked else None,
        )
        session.add(user)
        # Flush the user insert before the API key to satisfy FK constraints.
        await session.flush()
        session.add(api_key)
        if plan_id is not None:
            # Ensure tests have an explicit plan assignment for entitlement checks.
            now = _utc_now()
            result = await session.execute(
                select(TenantPlanAssignment).where(
                    TenantPlanAssignment.tenant_id == tenant_id,
                    TenantPlanAssignment.is_active.is_(True),
                )
            )
            assignment = result.scalar_one_or_none()
            if assignment is None or assignment.plan_id != plan_id:
                if assignment is not None:
                    assignment.is_active = False
                    assignment.effective_to = now
                session.add(
                    TenantPlanAssignment(
                        tenant_id=tenant_id,
                        plan_id=plan_id,
                        effective_from=now,
                        effective_to=None,
                        is_active=True,
                    )
                )
        if seed_authz_policies:
            await _seed_allow_policies(session=session, tenant_id=tenant_id)
        await session.commit()

    headers = {"Authorization": f"Bearer {raw_key}"}
    return raw_key, headers, user_id, key_id


async def _seed_allow_policies(*, session: AsyncSession, tenant_id: str) -> None:
    # Seed baseline allow policies so tests exercise ACLs without global denies.
    existing = (
        await session.execute(
            select(AuthorizationPolicy).where(
                AuthorizationPolicy.tenant_id == tenant_id,
                AuthorizationPolicy.name.in_(
                    {"test-allow-documents", "test-allow-run"},
                ),
            )
        )
    ).scalars().all()
    existing_names = {policy.name for policy in existing}
    if "test-allow-documents" not in existing_names:
        session.add(
            AuthorizationPolicy(
                id=uuid4().hex,
                tenant_id=tenant_id,
                name="test-allow-documents",
                version=1,
                effect="allow",
                resource_type="document",
                action="*",
                condition_json={},
                priority=10,
                enabled=True,
                created_by="test-suite",
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )
    if "test-allow-run" not in existing_names:
        session.add(
            AuthorizationPolicy(
                id=uuid4().hex,
                tenant_id=tenant_id,
                name="test-allow-run",
                version=1,
                effect="allow",
                resource_type="corpus",
                action="run",
                condition_json={},
                priority=10,
                enabled=True,
                created_by="test-suite",
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )
