from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from nexusrag.domain.models import Plan, PlanFeature, TenantFeatureOverride, TenantPlanAssignment
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.entitlements import (
    FEATURE_RETRIEVAL_AWS,
    FEATURE_RETRIEVAL_LOCAL,
    FEATURE_TTS,
    get_effective_entitlements,
    require_feature,
    reset_entitlements_cache,
)


@pytest.mark.asyncio
async def test_entitlements_merge_precedence() -> None:
    tenant_id = f"t-ent-{uuid4().hex}"
    plan_id = f"plan-{uuid4().hex}"
    now = datetime.now(timezone.utc)

    try:
        async with SessionLocal() as session:
            session.add(Plan(id=plan_id, name="Test Plan", is_active=True))
            session.add(
                PlanFeature(
                    plan_id=plan_id,
                    feature_key=FEATURE_RETRIEVAL_LOCAL,
                    enabled=True,
                )
            )
            session.add(
                TenantPlanAssignment(
                    tenant_id=tenant_id,
                    plan_id=plan_id,
                    effective_from=now,
                    effective_to=None,
                    is_active=True,
                )
            )
            session.add(
                TenantFeatureOverride(
                    tenant_id=tenant_id,
                    feature_key=FEATURE_TTS,
                    enabled=True,
                    config_json={"voices": ["nova"]},
                )
            )
            await session.commit()

        reset_entitlements_cache()
        async with SessionLocal() as session:
            entitlements = await get_effective_entitlements(session, tenant_id)

        assert entitlements[FEATURE_RETRIEVAL_LOCAL].enabled is True
        assert entitlements[FEATURE_TTS].enabled is True
        assert entitlements[FEATURE_TTS].config == {"voices": ["nova"]}
        # Features absent from the plan should default to disabled.
        assert entitlements[FEATURE_RETRIEVAL_AWS].enabled is False
    finally:
        reset_entitlements_cache()
        async with SessionLocal() as session:
            await session.execute(
                delete(TenantFeatureOverride).where(TenantFeatureOverride.tenant_id == tenant_id)
            )
            await session.execute(
                delete(TenantPlanAssignment).where(TenantPlanAssignment.tenant_id == tenant_id)
            )
            await session.execute(delete(PlanFeature).where(PlanFeature.plan_id == plan_id))
            await session.execute(delete(Plan).where(Plan.id == plan_id))
            await session.commit()


@pytest.mark.asyncio
async def test_require_feature_error_payload() -> None:
    tenant_id = f"t-ent-{uuid4().hex}"
    reset_entitlements_cache()

    async with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            await require_feature(session=session, tenant_id=tenant_id, feature_key=FEATURE_TTS)

    detail = exc.value.detail
    assert detail["code"] == "FEATURE_NOT_ENABLED"
    assert detail["feature_key"] == FEATURE_TTS
    assert "Feature not enabled" in detail["message"]
