from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.domain.models import ComplianceArtifact, ControlCatalog, ControlEvaluation, EvidenceBundle
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.compliance import (
    evaluate_all_controls,
    generate_evidence_bundle,
    get_latest_control_statuses,
    verify_evidence_bundle,
)


router = APIRouter(prefix="/admin/compliance", tags=["compliance"], responses=DEFAULT_ERROR_RESPONSES)


class ControlStatusResponse(BaseModel):
    control_id: str
    title: str
    trust_criteria: str
    severity: str
    status: str
    evaluated_at: str | None


class ComplianceEvaluateRequest(BaseModel):
    controls: list[str] | None = Field(default=None)
    window_days: int = Field(default=30, ge=1, le=365)
    trust_criteria: list[str] | None = Field(default=None)


class ComplianceEvaluateResponse(BaseModel):
    evaluated: int
    passed: int
    warned: int
    failed: int
    errored: int
    results: list[dict[str, Any]]


class ComplianceEvaluationResponse(BaseModel):
    id: int
    control_id: str
    status: str
    score: int | None
    evaluated_at: str
    window_start: str
    window_end: str
    findings_json: dict[str, Any] | None
    evidence_refs_json: dict[str, Any] | None


class BundleRequest(BaseModel):
    bundle_type: str
    period_start: datetime
    period_end: datetime


class BundleResponse(BaseModel):
    id: int
    status: str
    manifest_uri: str | None
    signature: str | None
    checksum_sha256: str | None
    generated_at: str | None


class BundleVerifyResponse(BaseModel):
    verified: bool
    message: str


class ArtifactRequest(BaseModel):
    artifact_type: str = Field(..., min_length=1)
    control_id: str | None = None
    artifact_uri: str | None = None
    checksum_sha256: str | None = None
    metadata_json: dict[str, Any] | None = None


class ArtifactResponse(BaseModel):
    id: int
    artifact_type: str
    control_id: str | None
    artifact_uri: str | None
    checksum_sha256: str | None
    created_at: str


def _ensure_compliance_enabled() -> None:
    settings = get_settings()
    if not settings.compliance_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "COMPLIANCE_DISABLED", "message": "Compliance automation is disabled"},
        )


@router.get(
    "/controls",
    response_model=SuccessEnvelope[list[ControlStatusResponse]] | list[ControlStatusResponse],
)
async def list_controls(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[ControlStatusResponse]:
    # Return control catalog entries with latest status for admins.
    _ = principal
    _ensure_compliance_enabled()
    statuses = await get_latest_control_statuses(db, tenant_scope=None)
    payload = [ControlStatusResponse(**row) for row in statuses]
    return success_response(request=request, data=payload)


@router.post(
    "/evaluate",
    response_model=SuccessEnvelope[ComplianceEvaluateResponse] | ComplianceEvaluateResponse,
)
async def evaluate_controls(
    request: Request,
    payload: ComplianceEvaluateRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ComplianceEvaluateResponse:
    # Run compliance control evaluations on demand.
    _ensure_compliance_enabled()
    try:
        results = await evaluate_all_controls(
            db,
            window_days=payload.window_days,
            tenant_scope=None,
            trust_criteria=payload.trust_criteria,
            control_ids=payload.controls,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "COMPLIANCE_EVALUATION_FAILED", "message": "Control evaluation failed"},
        ) from exc
    counts = {"pass": 0, "warn": 0, "fail": 0, "error": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="compliance.control.evaluated",
        outcome="success",
        resource_type="compliance",
        resource_id="evaluate",
        request_id=request_ctx["request_id"],
        metadata={"controls": payload.controls, "window_days": payload.window_days},
        commit=True,
        best_effort=True,
    )
    response = ComplianceEvaluateResponse(
        evaluated=len(results),
        passed=counts.get("pass", 0),
        warned=counts.get("warn", 0),
        failed=counts.get("fail", 0),
        errored=counts.get("error", 0),
        results=[
            {
                "control_id": result.control_id,
                "status": result.status,
                "score": result.score,
                "evaluated_at": result.evaluated_at.isoformat(),
            }
            for result in results
        ],
    )
    return success_response(request=request, data=response)


@router.get(
    "/evaluations",
    response_model=SuccessEnvelope[list[ComplianceEvaluationResponse]] | list[ComplianceEvaluationResponse],
)
async def list_evaluations(
    request: Request,
    control_id: str | None = None,
    status: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[ComplianceEvaluationResponse]:
    # List control evaluations with filtering for investigations.
    _ = principal
    _ensure_compliance_enabled()
    query = select(ControlEvaluation)
    if control_id:
        query = query.where(ControlEvaluation.control_id == control_id)
    if status:
        query = query.where(ControlEvaluation.status == status)
    if from_ts:
        query = query.where(ControlEvaluation.evaluated_at >= from_ts)
    if to_ts:
        query = query.where(ControlEvaluation.evaluated_at <= to_ts)
    query = query.order_by(ControlEvaluation.evaluated_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(query)).scalars().all()
    payload = [
        ComplianceEvaluationResponse(
            id=row.id,
            control_id=row.control_id,
            status=row.status,
            score=row.score,
            evaluated_at=row.evaluated_at.isoformat(),
            window_start=row.window_start.isoformat(),
            window_end=row.window_end.isoformat(),
            findings_json=row.findings_json,
            evidence_refs_json=row.evidence_refs_json,
        )
        for row in rows
    ]
    return success_response(request=request, data=payload)


@router.post(
    "/bundles",
    response_model=SuccessEnvelope[BundleResponse] | BundleResponse,
)
async def create_bundle(
    request: Request,
    payload: BundleRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> BundleResponse:
    # Generate a SOC 2 evidence bundle for auditors.
    _ensure_compliance_enabled()
    try:
        request_ctx = get_request_context(request)
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="compliance.bundle.requested",
            outcome="success",
            resource_type="evidence_bundle",
            resource_id="request",
            request_id=request_ctx["request_id"],
            metadata={"bundle_type": payload.bundle_type},
            commit=True,
            best_effort=True,
        )
        result = await generate_evidence_bundle(
            db,
            bundle_type=payload.bundle_type,
            period_start=payload.period_start,
            period_end=payload.period_end,
            tenant_scope=None,
            generated_by_actor_id=principal.api_key_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "COMPLIANCE_BUNDLE_BUILD_FAILED", "message": "Evidence bundle build failed"},
        ) from exc
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="compliance.bundle.generated",
        outcome="success",
        resource_type="evidence_bundle",
        resource_id=str(result.bundle_id),
        request_id=request_ctx["request_id"],
        metadata={"bundle_type": payload.bundle_type},
        commit=True,
        best_effort=True,
    )
    row = await db.get(EvidenceBundle, result.bundle_id)
    return success_response(
        request=request,
        data=BundleResponse(
            id=row.id,
            status=row.status,
            manifest_uri=row.manifest_uri,
            signature=row.signature,
            checksum_sha256=row.checksum_sha256,
            generated_at=row.generated_at.isoformat() if row.generated_at else None,
        ),
    )


@router.get(
    "/bundles/{bundle_id}",
    response_model=SuccessEnvelope[BundleResponse] | BundleResponse,
)
async def get_bundle(
    request: Request,
    bundle_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> BundleResponse:
    # Return metadata for evidence bundles.
    _ = principal
    _ensure_compliance_enabled()
    row = await db.get(EvidenceBundle, bundle_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMPLIANCE_CONTROL_NOT_FOUND", "message": "Evidence bundle not found"},
        )
    return success_response(
        request=request,
        data=BundleResponse(
            id=row.id,
            status=row.status,
            manifest_uri=row.manifest_uri,
            signature=row.signature,
            checksum_sha256=row.checksum_sha256,
            generated_at=row.generated_at.isoformat() if row.generated_at else None,
        ),
    )


@router.post(
    "/bundles/{bundle_id}/verify",
    response_model=SuccessEnvelope[BundleVerifyResponse] | BundleVerifyResponse,
)
async def verify_bundle(
    request: Request,
    bundle_id: int,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> BundleVerifyResponse:
    # Verify bundle signatures and checksums.
    _ = principal
    _ensure_compliance_enabled()
    verified, message = await verify_evidence_bundle(db, bundle_id=bundle_id)
    status = "success" if verified else "failure"
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type=f"compliance.bundle.verification.{status}",
        outcome=status,
        resource_type="evidence_bundle",
        resource_id=str(bundle_id),
        request_id=request_ctx["request_id"],
        metadata={"message": message},
        commit=True,
        best_effort=True,
    )
    if not verified:
        raise HTTPException(
            status_code=400,
            detail={"code": "COMPLIANCE_BUNDLE_VERIFY_FAILED", "message": message},
        )
    return success_response(request=request, data=BundleVerifyResponse(verified=verified, message=message))


@router.post(
    "/artifacts",
    response_model=SuccessEnvelope[ArtifactResponse] | ArtifactResponse,
)
async def create_artifact(
    request: Request,
    payload: ArtifactRequest,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ArtifactResponse:
    # Record manual compliance artifacts such as dependency scan attestations.
    _ = request
    _ensure_compliance_enabled()
    if payload.control_id:
        control = await db.get(ControlCatalog, payload.control_id)
        if control is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "COMPLIANCE_CONTROL_NOT_FOUND", "message": "Control not found"},
            )
    artifact = ComplianceArtifact(
        artifact_type=payload.artifact_type,
        control_id=payload.control_id,
        artifact_uri=payload.artifact_uri,
        checksum_sha256=payload.checksum_sha256,
        created_by_actor_id=principal.api_key_id,
        metadata_json=payload.metadata_json or {},
    )
    db.add(artifact)
    await db.commit()
    await db.refresh(artifact)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="compliance.artifact.recorded",
        outcome="success",
        resource_type="compliance_artifact",
        resource_id=str(artifact.id),
        metadata={"artifact_type": payload.artifact_type},
        commit=True,
        best_effort=True,
    )
    return success_response(
        request=request,
        data=ArtifactResponse(
            id=artifact.id,
            artifact_type=artifact.artifact_type,
            control_id=artifact.control_id,
            artifact_uri=artifact.artifact_uri,
            checksum_sha256=artifact.checksum_sha256,
            created_at=artifact.created_at.isoformat(),
        ),
    )
