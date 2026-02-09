from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio
import logging
import time
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import (
    Plan,
    PlanFeature,
    TenantFeatureOverride,
    TenantPlanAssignment,
)


logger = logging.getLogger(__name__)

DEFAULT_PLAN_ID = "free"
ENTITLEMENT_CACHE_TTL_S = 30

FEATURE_RETRIEVAL_LOCAL = "feature.retrieval.local_pgvector"
FEATURE_RETRIEVAL_AWS = "feature.retrieval.aws_bedrock"
FEATURE_RETRIEVAL_GCP = "feature.retrieval.gcp_vertex"
FEATURE_TTS = "feature.tts"
FEATURE_OPS_ADMIN = "feature.ops_admin_access"
FEATURE_AUDIT = "feature.audit_access"
FEATURE_HIGH_QUOTA = "feature.high_quota_tier"
FEATURE_CORPORA_PATCH_PROVIDER = "feature.corpora_patch_provider_config"
FEATURE_BILLING_WEBHOOK_TEST = "feature.billing_webhook_test"

FEATURE_KEYS = {
    FEATURE_RETRIEVAL_LOCAL,
    FEATURE_RETRIEVAL_AWS,
    FEATURE_RETRIEVAL_GCP,
    FEATURE_TTS,
    FEATURE_OPS_ADMIN,
    FEATURE_AUDIT,
    FEATURE_HIGH_QUOTA,
    FEATURE_CORPORA_PATCH_PROVIDER,
    FEATURE_BILLING_WEBHOOK_TEST,
}

RETRIEVAL_PROVIDER_FEATURES = {
    "local_pgvector": FEATURE_RETRIEVAL_LOCAL,
    "aws_bedrock_kb": FEATURE_RETRIEVAL_AWS,
    "gcp_vertex": FEATURE_RETRIEVAL_GCP,
}


@dataclass(frozen=True)
class FeatureEntitlement:
    # Capture feature flags plus optional configuration payloads.
    enabled: bool
    config: dict[str, Any] | None = None


_entitlement_cache: dict[str, tuple[float, dict[str, FeatureEntitlement]]] = {}
_entitlement_cache_lock = asyncio.Lock()


def _feature_not_enabled_error(feature_key: str) -> HTTPException:
    # Use a stable 403 payload when entitlements block a feature.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "FEATURE_NOT_ENABLED",
            "message": "Feature not enabled for tenant plan",
            "feature_key": feature_key,
        },
    )


async def get_effective_entitlements(
    session: AsyncSession,
    tenant_id: str,
) -> dict[str, FeatureEntitlement]:
    # Return effective entitlements with a short-lived cache to reduce DB load.
    now = time.time()
    cached = _entitlement_cache.get(tenant_id)
    if cached and cached[0] > now:
        return cached[1]

    entitlements = await _compute_entitlements(session, tenant_id)
    async with _entitlement_cache_lock:
        _entitlement_cache[tenant_id] = (now + ENTITLEMENT_CACHE_TTL_S, entitlements)
    return entitlements


def invalidate_entitlements_cache(tenant_id: str) -> None:
    # Drop cached entitlements after plan/override updates.
    _entitlement_cache.pop(tenant_id, None)


def reset_entitlements_cache() -> None:
    # Clear cached entitlements for deterministic tests.
    _entitlement_cache.clear()


async def require_feature(
    *,
    session: AsyncSession,
    tenant_id: str,
    feature_key: str,
) -> None:
    # Enforce tenant entitlements for a single feature.
    entitlements = await get_effective_entitlements(session, tenant_id)
    entitlement = entitlements.get(feature_key, FeatureEntitlement(False, None))
    if not entitlement.enabled:
        raise _feature_not_enabled_error(feature_key)


async def require_retrieval_provider(
    *,
    session: AsyncSession,
    tenant_id: str,
    provider_name: str,
) -> None:
    # Map retrieval providers to entitlements for gating.
    feature_key = RETRIEVAL_PROVIDER_FEATURES.get(provider_name)
    if feature_key is None:
        return
    await require_feature(session=session, tenant_id=tenant_id, feature_key=feature_key)


async def list_plan_catalog(session: AsyncSession) -> list[Plan]:
    # Return active plan catalog entries for admin discovery.
    result = await session.execute(select(Plan).order_by(Plan.id))
    return list(result.scalars().all())


async def list_plan_features(session: AsyncSession, plan_ids: list[str]) -> list[PlanFeature]:
    # Fetch plan features for a set of plan ids in a single query.
    if not plan_ids:
        return []
    result = await session.execute(
        select(PlanFeature).where(PlanFeature.plan_id.in_(plan_ids)).order_by(PlanFeature.feature_key)
    )
    return list(result.scalars().all())


async def get_active_plan_assignment(
    session: AsyncSession, tenant_id: str
) -> TenantPlanAssignment | None:
    # Select the active plan assignment for the tenant if present.
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(TenantPlanAssignment)
        .where(
            TenantPlanAssignment.tenant_id == tenant_id,
            TenantPlanAssignment.is_active.is_(True),
            TenantPlanAssignment.effective_from <= now,
            or_(TenantPlanAssignment.effective_to.is_(None), TenantPlanAssignment.effective_to > now),
        )
        .order_by(TenantPlanAssignment.effective_from.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _compute_entitlements(
    session: AsyncSession, tenant_id: str
) -> dict[str, FeatureEntitlement]:
    plan_id = await _resolve_plan_id(session, tenant_id)
    plan_features = await _load_plan_features(session, plan_id)
    overrides = await _load_overrides(session, tenant_id)

    entitlements: dict[str, FeatureEntitlement] = {
        key: FeatureEntitlement(False, None) for key in FEATURE_KEYS
    }

    for feature in plan_features:
        entitlements[feature.feature_key] = FeatureEntitlement(
            enabled=bool(feature.enabled),
            config=feature.config_json,
        )

    for override in overrides:
        current = entitlements.get(override.feature_key, FeatureEntitlement(False, None))
        enabled = current.enabled if override.enabled is None else bool(override.enabled)
        config = current.config if override.config_json is None else override.config_json
        entitlements[override.feature_key] = FeatureEntitlement(enabled=enabled, config=config)

    return entitlements


async def _resolve_plan_id(session: AsyncSession, tenant_id: str) -> str:
    assignment = await get_active_plan_assignment(session, tenant_id)
    if assignment is None:
        return DEFAULT_PLAN_ID
    return assignment.plan_id


async def _load_plan_features(session: AsyncSession, plan_id: str) -> list[PlanFeature]:
    result = await session.execute(select(PlanFeature).where(PlanFeature.plan_id == plan_id))
    features = list(result.scalars().all())
    if features or plan_id == DEFAULT_PLAN_ID:
        return features
    # Fall back to the default plan when assignments reference missing plan ids.
    logger.warning("plan_features_missing plan_id=%s", plan_id)
    result = await session.execute(select(PlanFeature).where(PlanFeature.plan_id == DEFAULT_PLAN_ID))
    return list(result.scalars().all())


async def _load_overrides(session: AsyncSession, tenant_id: str) -> list[TenantFeatureOverride]:
    result = await session.execute(
        select(TenantFeatureOverride).where(TenantFeatureOverride.tenant_id == tenant_id)
    )
    return list(result.scalars().all())
