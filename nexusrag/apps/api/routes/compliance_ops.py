from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.core.config import get_settings
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.domain.models import EvidenceBundle
from nexusrag.services.compliance import get_latest_control_statuses


router = APIRouter(prefix="/ops/compliance", tags=["ops"], responses=DEFAULT_ERROR_RESPONSES)


class ComplianceStatusResponse(BaseModel):
    controls_passed: int
    controls_warn: int
    controls_failed: int
    controls_errored: int
    last_bundle_at: str | None
    status: str


@router.get(
    "/status",
    response_model=SuccessEnvelope[ComplianceStatusResponse] | ComplianceStatusResponse,
)
async def compliance_status(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ComplianceStatusResponse:
    # Provide an at-a-glance compliance posture summary for ops dashboards.
    _ = principal
    if not get_settings().compliance_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "COMPLIANCE_DISABLED", "message": "Compliance automation is disabled"},
        )
    rows = await get_latest_control_statuses(db, tenant_scope=None)
    counts = {"pass": 0, "warn": 0, "fail": 0, "error": 0}
    last_bundle_at = None
    latest_bundle = (
        await db.execute(
            select(EvidenceBundle)
            .where(EvidenceBundle.status == "ready")
            .order_by(EvidenceBundle.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_bundle and latest_bundle.generated_at:
        last_bundle_at = latest_bundle.generated_at.isoformat()
    for row in rows:
        status = row.get("status")
        if status in counts:
            counts[status] += 1
    posture = "healthy"
    if counts["fail"] > 0 or counts["error"] > 0:
        posture = "non_compliant"
    elif counts["warn"] > 0:
        posture = "at_risk"
    response = ComplianceStatusResponse(
        controls_passed=counts["pass"],
        controls_warn=counts["warn"],
        controls_failed=counts["fail"],
        controls_errored=counts["error"],
        last_bundle_at=last_bundle_at,
        status=posture,
    )
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="ops.viewed",
        outcome="success",
        resource_type="ops",
        resource_id="compliance_status",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"path": request.url.path},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=response)
