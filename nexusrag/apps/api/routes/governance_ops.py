from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.entitlements import FEATURE_OPS_ADMIN, require_feature
from nexusrag.services.governance import governance_evidence, governance_status_snapshot


router = APIRouter(prefix="/ops/governance", tags=["ops"], responses=DEFAULT_ERROR_RESPONSES)


class GovernanceStatusResponse(BaseModel):
    policy_engine_enabled: bool
    active_holds_count: int
    pending_dsar_count: int
    last_retention_run: dict[str, Any]
    compliance_posture: str


class GovernanceEvidenceResponse(BaseModel):
    retention_runs: list[dict[str, Any]]
    dsar_requests: list[dict[str, Any]]
    legal_holds: list[dict[str, Any]]
    policy_changes: list[dict[str, Any]]


@router.get(
    "/status",
    response_model=SuccessEnvelope[GovernanceStatusResponse] | GovernanceStatusResponse,
)
async def governance_status(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> GovernanceStatusResponse:
    # Restrict governance posture visibility to tenant admins with ops entitlement.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    snapshot = await governance_status_snapshot(db, principal.tenant_id)
    return success_response(request=request, data=GovernanceStatusResponse(**snapshot))


@router.get(
    "/evidence",
    response_model=SuccessEnvelope[GovernanceEvidenceResponse] | GovernanceEvidenceResponse,
)
async def governance_evidence_bundle(
    request: Request,
    window_days: int = Query(default=30, ge=1, le=365),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> GovernanceEvidenceResponse:
    # Build machine-readable evidence metadata for audit preparation.
    await require_feature(
        session=db,
        tenant_id=principal.tenant_id,
        feature_key=FEATURE_OPS_ADMIN,
    )
    try:
        bundle = await governance_evidence(db, tenant_id=principal.tenant_id, window_days=window_days)
    except Exception as exc:  # noqa: BLE001 - surface a stable contract for evidence failures.
        raise HTTPException(
            status_code=503,
            detail={"code": "GOVERNANCE_REPORT_UNAVAILABLE", "message": "Governance evidence is unavailable"},
        ) from exc
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="governance.evidence.generated",
        outcome="success",
        resource_type="governance",
        resource_id="evidence",
        request_id=request_ctx["request_id"],
        metadata={"window_days": window_days},
        commit=True,
        best_effort=True,
    )
    return success_response(
        request=request,
        data=GovernanceEvidenceResponse(
            retention_runs=bundle.retention_runs,
            dsar_requests=bundle.dsar_requests,
            legal_holds=bundle.legal_holds,
            policy_changes=bundle.policy_changes,
        ),
    )
