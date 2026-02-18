from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, idempotency_key_header, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    Plan,
    PlanFeature,
    PlanLimit,
    RetentionRun,
    TenantFeatureOverride,
    TenantPlanAssignment,
    UsageCounter,
)
from nexusrag.services.entitlements import (
    DEFAULT_PLAN_ID,
    FEATURE_KEYS,
    FeatureEntitlement,
    get_active_plan_assignment,
    get_effective_entitlements,
    invalidate_entitlements_cache,
    list_plan_catalog,
    list_plan_features,
)
from nexusrag.services.quota import parse_period_start
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)
from nexusrag.services.rollouts import (
    CANARY_KEYS,
    KILL_SWITCH_KEYS,
    get_canary_percentages,
    get_kill_switches,
    set_canary_percentages,
    set_kill_switches,
)
from nexusrag.services.maintenance import (
    cleanup_ui_actions,
    backup_create_scheduled,
    backup_prune_retention,
    prune_audit_events,
    prune_idempotency,
    prune_usage_counters,
    restore_drill_scheduled,
    compliance_evaluate_scheduled,
    compliance_bundle_periodic,
    compliance_prune_old_evidence,
    prune_retention_all,
    record_retention_run,
)
from nexusrag.services.governance import enforce_policy, get_or_create_retention_policy


router = APIRouter(prefix="/admin", tags=["admin"], responses=DEFAULT_ERROR_RESPONSES)


class PlanLimitResponse(BaseModel):
    tenant_id: str
    daily_requests_limit: int | None
    monthly_requests_limit: int | None
    daily_tokens_limit: int | None
    monthly_tokens_limit: int | None
    soft_cap_ratio: float
    hard_cap_enabled: bool


class PlanLimitPatchRequest(BaseModel):
    daily_requests_limit: int | None = Field(default=None, ge=0)
    monthly_requests_limit: int | None = Field(default=None, ge=0)
    daily_tokens_limit: int | None = Field(default=None, ge=0)
    monthly_tokens_limit: int | None = Field(default=None, ge=0)
    soft_cap_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    hard_cap_enabled: bool | None = Field(default=None)


class UsageSummaryResponse(BaseModel):
    tenant_id: str
    period_type: str
    period_start: str
    requests_count: int
    estimated_tokens_count: int | None


class PlanFeatureResponse(BaseModel):
    feature_key: str
    enabled: bool
    config_json: dict[str, Any] | None


class PlanResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    features: list[PlanFeatureResponse]


class TenantPlanResponse(BaseModel):
    tenant_id: str
    plan_id: str
    plan_name: str | None
    effective_from: str | None
    effective_to: str | None
    is_active: bool
    entitlements: list[PlanFeatureResponse]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "tenant_id": "tenant_123",
                    "plan_id": "pro",
                    "plan_name": "Pro",
                    "effective_from": "2026-02-01T00:00:00Z",
                    "effective_to": None,
                    "is_active": True,
                    "entitlements": [
                        {
                            "feature_key": "feature.retrieval.local_pgvector",
                            "enabled": True,
                            "config_json": None,
                        },
                        {
                            "feature_key": "feature.tts",
                            "enabled": True,
                            "config_json": None,
                        },
                    ],
                }
            ]
        }
    }


class PlanAssignmentRequest(BaseModel):
    plan_id: str


class FeatureOverrideRequest(BaseModel):
    feature_key: str
    enabled: bool | None = None
    config_json: dict[str, Any] | None = None


class KillSwitchesResponse(BaseModel):
    # Report active kill switches for operational visibility.
    kill_switches: dict[str, bool]


class KillSwitchesPatchRequest(BaseModel):
    # Allow partial updates to kill switches.
    kill_switches: dict[str, bool]


class CanaryResponse(BaseModel):
    # Report rollout percentages for canary-controlled features.
    canary_percentages: dict[str, int]


class CanaryPatchRequest(BaseModel):
    # Allow partial updates to canary percentages.
    canary_percentages: dict[str, int]


class MaintenanceRunResponse(BaseModel):
    # Report maintenance task execution status and affected rows.
    task: str
    status: str
    deleted_rows: int


class RetentionStatusResponse(BaseModel):
    # Report configured retention windows and recent maintenance execution proofs.
    tenant_id: str
    configured_days: dict[str, int | None]
    last_run_by_task: dict[str, str | None]
    next_schedule: str


def _ensure_same_tenant(principal: Principal, tenant_id: str) -> None:
    # Keep admin endpoints scoped to the caller's tenant.
    if tenant_id != principal.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant scope does not match admin key")


def _to_plan_response(tenant_id: str, plan: PlanLimit | None) -> PlanLimitResponse:
    # Return default quota settings when no plan limits are configured.
    return PlanLimitResponse(
        tenant_id=tenant_id,
        daily_requests_limit=plan.daily_requests_limit if plan else None,
        monthly_requests_limit=plan.monthly_requests_limit if plan else None,
        daily_tokens_limit=plan.daily_tokens_limit if plan else None,
        monthly_tokens_limit=plan.monthly_tokens_limit if plan else None,
        soft_cap_ratio=plan.soft_cap_ratio if plan else 0.8,
        hard_cap_enabled=plan.hard_cap_enabled if plan else True,
    )


# Allow legacy unwrapped responses; v1 middleware wraps envelopes.
@router.get(
    "/quotas/{tenant_id}",
    response_model=SuccessEnvelope[PlanLimitResponse] | PlanLimitResponse,
)
async def get_quota_limits(
    tenant_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PlanLimitResponse:
    # Allow admins to view quota limits for their tenant.
    _ensure_same_tenant(principal, tenant_id)
    try:
        result = await db.execute(select(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
        plan = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching quota limits") from exc
    return _to_plan_response(tenant_id, plan)


@router.patch(
    "/quotas/{tenant_id}",
    response_model=SuccessEnvelope[PlanLimitResponse] | PlanLimitResponse,
)
async def patch_quota_limits(
    tenant_id: str,
    request: Request,
    payload: PlanLimitPatchRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[PlanLimitResponse] | PlanLimitResponse:
    # Allow admins to update quota limits for their tenant.
    _ensure_same_tenant(principal, tenant_id)
    request_hash = compute_request_hash(
        {"tenant_id": tenant_id, "payload": payload.model_dump()}
    )
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)
    try:
        result = await db.execute(select(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
        plan = result.scalar_one_or_none()
        if plan is None:
            plan = PlanLimit(tenant_id=tenant_id)
            db.add(plan)

        if payload.daily_requests_limit is not None:
            plan.daily_requests_limit = payload.daily_requests_limit
        if payload.monthly_requests_limit is not None:
            plan.monthly_requests_limit = payload.monthly_requests_limit
        if payload.daily_tokens_limit is not None:
            plan.daily_tokens_limit = payload.daily_tokens_limit
        if payload.monthly_tokens_limit is not None:
            plan.monthly_tokens_limit = payload.monthly_tokens_limit
        if payload.soft_cap_ratio is not None:
            plan.soft_cap_ratio = payload.soft_cap_ratio
        if payload.hard_cap_enabled is not None:
            plan.hard_cap_enabled = payload.hard_cap_enabled

        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while updating quota limits") from exc

    response_payload = _to_plan_response(tenant_id, plan)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=200,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.get(
    "/usage/{tenant_id}",
    response_model=SuccessEnvelope[UsageSummaryResponse] | UsageSummaryResponse,
)
async def get_usage_summary(
    tenant_id: str,
    period: str = Query(default="day", pattern="^(day|month)$"),
    start: date = Query(...),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> UsageSummaryResponse:
    # Return usage summaries for day/month periods for admin review.
    _ensure_same_tenant(principal, tenant_id)
    period_start = parse_period_start(period, start)
    try:
        result = await db.execute(
            select(UsageCounter).where(
                UsageCounter.tenant_id == tenant_id,
                UsageCounter.period_type == period,
                UsageCounter.period_start == period_start,
            )
        )
        counter = result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching usage") from exc

    return UsageSummaryResponse(
        tenant_id=tenant_id,
        period_type=period,
        period_start=period_start.isoformat(),
        requests_count=int(counter.requests_count) if counter else 0,
        estimated_tokens_count=counter.estimated_tokens_count if counter else None,
    )


def _feature_response(feature_key: str, entitlement: FeatureEntitlement) -> PlanFeatureResponse:
    # Normalize entitlements for API responses.
    return PlanFeatureResponse(
        feature_key=feature_key,
        enabled=entitlement.enabled,
        config_json=entitlement.config,
    )


def _feature_from_plan(feature: PlanFeature) -> PlanFeatureResponse:
    # Serialize plan features for catalog listing.
    return PlanFeatureResponse(
        feature_key=feature.feature_key,
        enabled=bool(feature.enabled),
        config_json=feature.config_json,
    )


async def _build_tenant_plan_response(
    db: AsyncSession,
    tenant_id: str,
) -> TenantPlanResponse:
    # Combine assignment + entitlements into a tenant-specific response.
    assignment = await get_active_plan_assignment(db, tenant_id)
    plan_id = assignment.plan_id if assignment else DEFAULT_PLAN_ID

    plan = None
    try:
        result = await db.execute(select(Plan).where(Plan.id == plan_id))
        plan = result.scalar_one_or_none()
    except SQLAlchemyError:
        plan = None

    entitlements = await get_effective_entitlements(db, tenant_id)
    features = [
        _feature_response(feature_key, entitlements.get(feature_key, FeatureEntitlement(False, None)))
        for feature_key in sorted(FEATURE_KEYS)
    ]
    return TenantPlanResponse(
        tenant_id=tenant_id,
        plan_id=plan_id,
        plan_name=plan.name if plan else None,
        effective_from=assignment.effective_from.isoformat() if assignment else None,
        effective_to=assignment.effective_to.isoformat() if assignment and assignment.effective_to else None,
        is_active=assignment.is_active if assignment else False,
        entitlements=features,
    )


@router.get("/plans", response_model=SuccessEnvelope[list[PlanResponse]] | list[PlanResponse])
async def list_plans(
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[PlanResponse]:
    # Allow tenant admins to discover plan catalogs.
    try:
        plans = await list_plan_catalog(db)
        plan_features = await list_plan_features(db, [plan.id for plan in plans])
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while fetching plans") from exc

    features_by_plan: dict[str, list[PlanFeatureResponse]] = {}
    for feature in plan_features:
        features_by_plan.setdefault(feature.plan_id, []).append(_feature_from_plan(feature))

    return [
        PlanResponse(
            id=plan.id,
            name=plan.name,
            is_active=plan.is_active,
            features=features_by_plan.get(plan.id, []),
        )
        for plan in plans
    ]


@router.get(
    "/plans/{tenant_id}",
    response_model=SuccessEnvelope[TenantPlanResponse] | TenantPlanResponse,
)
async def get_tenant_plan(
    tenant_id: str,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> TenantPlanResponse:
    # Allow tenant admins to view their current plan assignment.
    _ensure_same_tenant(principal, tenant_id)
    return await _build_tenant_plan_response(db, tenant_id)


@router.patch(
    "/plans/{tenant_id}",
    response_model=SuccessEnvelope[TenantPlanResponse] | TenantPlanResponse,
)
async def assign_tenant_plan(
    tenant_id: str,
    request: Request,
    payload: PlanAssignmentRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[TenantPlanResponse] | TenantPlanResponse:
    # Allow tenant admins to update plan assignments.
    _ensure_same_tenant(principal, tenant_id)
    request_hash = compute_request_hash(
        {"tenant_id": tenant_id, "payload": payload.model_dump()}
    )
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)
    try:
        result = await db.execute(select(Plan).where(Plan.id == payload.plan_id))
        plan = result.scalar_one_or_none()
        if plan is None or not plan.is_active:
            raise HTTPException(status_code=404, detail="Plan not found")

        now = datetime.now(timezone.utc)
        current = await get_active_plan_assignment(db, tenant_id)
        if current and current.plan_id == payload.plan_id:
            response_payload = await _build_tenant_plan_response(db, tenant_id)
            payload_body = success_response(request=request, data=response_payload)
            await store_idempotency_response(
                db=db,
                context=idempotency_ctx,
                response_status=200,
                response_body=jsonable_encoder(payload_body),
            )
            return payload_body

        if current:
            current.is_active = False
            current.effective_to = now

        db.add(
            TenantPlanAssignment(
                tenant_id=tenant_id,
                plan_id=payload.plan_id,
                effective_from=now,
                effective_to=None,
                is_active=True,
            )
        )
        await db.commit()
        invalidate_entitlements_cache(tenant_id)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while updating plan assignment") from exc

    response_payload = await _build_tenant_plan_response(db, tenant_id)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=200,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.patch(
    "/plans/{tenant_id}/overrides",
    response_model=SuccessEnvelope[TenantPlanResponse] | TenantPlanResponse,
)
async def patch_tenant_overrides(
    tenant_id: str,
    request: Request,
    payload: FeatureOverrideRequest,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[TenantPlanResponse] | TenantPlanResponse:
    # Allow tenant admins to override feature entitlements for their tenant.
    _ensure_same_tenant(principal, tenant_id)
    if payload.feature_key not in FEATURE_KEYS:
        raise HTTPException(status_code=422, detail="Unknown feature_key")
    request_hash = compute_request_hash(
        {"tenant_id": tenant_id, "payload": payload.model_dump()}
    )
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=principal.tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    try:
        result = await db.execute(
            select(TenantFeatureOverride).where(
                TenantFeatureOverride.tenant_id == tenant_id,
                TenantFeatureOverride.feature_key == payload.feature_key,
            )
        )
        override = result.scalar_one_or_none()
        if override is None:
            override = TenantFeatureOverride(
                tenant_id=tenant_id,
                feature_key=payload.feature_key,
            )
            db.add(override)

        if payload.enabled is not None:
            override.enabled = payload.enabled
        if payload.config_json is not None:
            override.config_json = payload.config_json

        await db.commit()
        invalidate_entitlements_cache(tenant_id)
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while updating overrides") from exc

    response_payload = await _build_tenant_plan_response(db, tenant_id)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=200,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.get(
    "/rollouts/killswitches",
    response_model=SuccessEnvelope[KillSwitchesResponse] | KillSwitchesResponse,
)
async def get_rollout_killswitches(
    principal: Principal = Depends(require_role("admin")),
) -> KillSwitchesResponse:
    # Allow admins to inspect active kill switches.
    _ = principal
    switches = await get_kill_switches()
    return KillSwitchesResponse(kill_switches=switches)


@router.patch(
    "/rollouts/killswitches",
    response_model=SuccessEnvelope[KillSwitchesResponse] | KillSwitchesResponse,
)
async def patch_rollout_killswitches(
    payload: KillSwitchesPatchRequest,
    principal: Principal = Depends(require_role("admin")),
) -> KillSwitchesResponse:
    # Allow admins to toggle kill switches for incident response.
    _ = principal
    allowed = set(KILL_SWITCH_KEYS.keys())
    updates = {key: bool(value) for key, value in payload.kill_switches.items() if key in allowed}
    if not updates:
        raise HTTPException(status_code=422, detail="No valid kill switches supplied")
    await set_kill_switches(updates)
    return KillSwitchesResponse(kill_switches=await get_kill_switches())


@router.get(
    "/rollouts/canary",
    response_model=SuccessEnvelope[CanaryResponse] | CanaryResponse,
)
async def get_rollout_canary(
    principal: Principal = Depends(require_role("admin")),
) -> CanaryResponse:
    # Allow admins to inspect canary rollout percentages.
    _ = principal
    percentages = await get_canary_percentages()
    return CanaryResponse(canary_percentages=percentages)


@router.patch(
    "/rollouts/canary",
    response_model=SuccessEnvelope[CanaryResponse] | CanaryResponse,
)
async def patch_rollout_canary(
    payload: CanaryPatchRequest,
    principal: Principal = Depends(require_role("admin")),
) -> CanaryResponse:
    # Allow admins to update canary rollout percentages.
    _ = principal
    allowed = set(CANARY_KEYS.keys())
    updates: dict[str, int] = {}
    for key, value in payload.canary_percentages.items():
        if key not in allowed:
            continue
        pct = max(0, min(int(value), 100))
        updates[key] = pct
    if not updates:
        raise HTTPException(status_code=422, detail="No valid canary percentages supplied")
    await set_canary_percentages(updates)
    return CanaryResponse(canary_percentages=await get_canary_percentages())


@router.post(
    "/maintenance/run",
    response_model=SuccessEnvelope[MaintenanceRunResponse] | MaintenanceRunResponse,
)
async def run_maintenance_task(
    request: Request,
    task: str = Query(
        ...,
        pattern="^(prune_idempotency|prune_audit|cleanup_actions|prune_usage|prune_retention_all|backup_create_scheduled|backup_prune_retention|restore_drill_scheduled|compliance_evaluate_scheduled|compliance_bundle_periodic|compliance_prune_old_evidence)$",
    ),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceRunResponse:
    # Allow admins to run bounded maintenance tasks on demand.
    _ = principal
    task_map = {
        "prune_idempotency": prune_idempotency,
        "prune_audit": prune_audit_events,
        "cleanup_actions": cleanup_ui_actions,
        "prune_usage": prune_usage_counters,
        "prune_retention_all": None,
        "backup_create_scheduled": backup_create_scheduled,
        "backup_prune_retention": backup_prune_retention,
        "restore_drill_scheduled": restore_drill_scheduled,
        "compliance_evaluate_scheduled": compliance_evaluate_scheduled,
        "compliance_bundle_periodic": compliance_bundle_periodic,
        "compliance_prune_old_evidence": compliance_prune_old_evidence,
    }
    runner = task_map.get(task)
    if runner is None and task != "prune_retention_all":
        raise HTTPException(status_code=422, detail="Unknown maintenance task")
    if task in {"backup_prune_retention"}:
        # Apply governance policy checks before destructive backup pruning.
        await enforce_policy(
            session=db,
            tenant_id=principal.tenant_id,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            rule_key="backup.prune",
            context={
                "endpoint": request.url.path,
                "method": request.method,
                "resource_type": "backup_set",
                "task": task,
                "actor_role": principal.role,
            },
            request_id=request.headers.get("X-Request-Id"),
        )
    retention_details: dict[str, object] | None = None
    if task == "prune_retention_all":
        # Run all retention paths together to provide a single governance-proof artifact.
        counters = await prune_retention_all(
            db,
            tenant_id=principal.tenant_id,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            request_id=request.headers.get("X-Request-Id"),
        )
        deleted = sum(int(value) for value in counters.values())
        retention_details = {"counters": counters, "deleted_rows": deleted}
    else:
        deleted = await runner(db)
        if task in {"prune_audit", "cleanup_actions", "prune_usage"}:
            retention_details = {"deleted_rows": deleted}
    if retention_details is not None:
        await record_retention_run(
            session=db,
            tenant_id=principal.tenant_id,
            task=task,
            outcome="success",
            details_json=retention_details,
        )
    await db.commit()
    payload = MaintenanceRunResponse(task=task, status="completed", deleted_rows=deleted)
    return success_response(request=request, data=payload)


@router.get(
    "/retention/status",
    response_model=SuccessEnvelope[RetentionStatusResponse] | RetentionStatusResponse,
)
async def get_retention_status(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> RetentionStatusResponse:
    # Provide retention configuration and last-run timestamps as compliance proof points.
    policy = await get_or_create_retention_policy(db, principal.tenant_id)
    rows = (
        await db.execute(
            select(RetentionRun)
            .where(RetentionRun.tenant_id == principal.tenant_id)
            .order_by(RetentionRun.last_run_at.desc())
            .limit(200)
        )
    ).scalars().all()
    last_run_by_task: dict[str, str | None] = {}
    for row in rows:
        if row.task in last_run_by_task:
            continue
        last_run_by_task[row.task] = row.last_run_at.isoformat() if row.last_run_at else None
    payload = RetentionStatusResponse(
        tenant_id=principal.tenant_id,
        configured_days={
            "audit": get_settings().audit_retention_days,
            "usage": get_settings().usage_counter_retention_days,
            "ui_actions": get_settings().ui_action_retention_days,
            "documents": policy.documents_ttl_days,
            "backups": policy.backups_ttl_days,
        },
        last_run_by_task=last_run_by_task,
        next_schedule="manual",
    )
    return success_response(request=request, data=payload)
