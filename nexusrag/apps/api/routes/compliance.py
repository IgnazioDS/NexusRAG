from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal, get_db, require_role
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.core.config import get_settings
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.compliance import (
    build_bundle_archive,
    create_compliance_snapshot,
    get_compliance_snapshot,
    list_compliance_snapshots,
)


router = APIRouter(prefix="/admin/compliance", tags=["compliance"], responses=DEFAULT_ERROR_RESPONSES)


class ComplianceSnapshotResponse(BaseModel):
    id: str
    tenant_id: str | None
    captured_at: str
    created_at: str
    created_by: str | None
    status: str
    results_json: dict
    summary_json: dict
    controls_json: list[dict]
    artifact_paths_json: dict


def _ensure_enabled() -> None:
    if not get_settings().compliance_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "COMPLIANCE_DISABLED", "message": "Compliance automation is disabled"},
        )


def _to_payload(row) -> ComplianceSnapshotResponse:
    # Return canonical snapshot fields and retain legacy aliases for backward compatible clients.
    captured_at = row.captured_at or row.created_at
    results_json = row.results_json or {"summary": row.summary_json, "controls": row.controls_json}
    return ComplianceSnapshotResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        captured_at=captured_at.isoformat() if captured_at else "",
        created_at=row.created_at.isoformat() if row.created_at else "",
        created_by=row.created_by,
        status=row.status,
        results_json=results_json,
        summary_json=row.summary_json,
        controls_json=row.controls_json,
        artifact_paths_json=row.artifact_paths_json or {},
    )


@router.post(
    "/snapshot",
    response_model=SuccessEnvelope[ComplianceSnapshotResponse] | ComplianceSnapshotResponse,
)
async def create_snapshot(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ComplianceSnapshotResponse:
    # Capture a point-in-time compliance posture snapshot for evidence generation.
    _ensure_enabled()
    row = await create_compliance_snapshot(
        db,
        tenant_id=principal.tenant_id,
        created_by=principal.api_key_id,
    )
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="compliance.snapshot.created",
        outcome="success",
        resource_type="compliance_snapshot",
        resource_id=row.id,
        request_id=request_ctx["request_id"],
        metadata={"status": row.status},
        commit=True,
        best_effort=True,
    )
    return success_response(request=request, data=_to_payload(row))


@router.post(
    "/snapshots",
    response_model=SuccessEnvelope[ComplianceSnapshotResponse] | ComplianceSnapshotResponse,
)
async def create_snapshot_plural(
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ComplianceSnapshotResponse:
    # Keep plural snapshot contract as an alias for client compatibility during rollout updates.
    return await create_snapshot(request=request, principal=principal, db=db)


@router.get(
    "/snapshots",
    response_model=SuccessEnvelope[list[ComplianceSnapshotResponse]] | list[ComplianceSnapshotResponse],
)
async def get_snapshots(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[ComplianceSnapshotResponse]:
    # Return newest-first snapshots to support auditor evidence workflows.
    _ensure_enabled()
    rows = await list_compliance_snapshots(db, tenant_id=principal.tenant_id, limit=limit)
    return success_response(request=request, data=[_to_payload(row) for row in rows])


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=SuccessEnvelope[ComplianceSnapshotResponse] | ComplianceSnapshotResponse,
)
async def get_snapshot(
    snapshot_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ComplianceSnapshotResponse:
    # Enforce tenant scoping when reading persisted compliance snapshots.
    _ensure_enabled()
    row = await get_compliance_snapshot(db, tenant_id=principal.tenant_id, snapshot_id=snapshot_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Snapshot not found"})
    return success_response(request=request, data=_to_payload(row))


@router.get("/bundle/{snapshot_id}.zip")
async def get_snapshot_bundle(
    snapshot_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Build evidence bundles in-memory so no unredacted temporary files are left on disk.
    _ensure_enabled()
    row = await get_compliance_snapshot(db, tenant_id=principal.tenant_id, snapshot_id=snapshot_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Snapshot not found"})
    archive = await build_bundle_archive(db, row)
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="compliance.bundle.generated",
        outcome="success",
        resource_type="compliance_snapshot",
        resource_id=row.id,
        request_id=request_ctx["request_id"],
        metadata={"format": "zip", "size_bytes": len(archive)},
        commit=True,
        best_effort=True,
    )
    headers = {"Content-Disposition": f'attachment; filename="compliance-bundle-{snapshot_id}.zip"'}
    return Response(content=archive, media_type="application/zip", headers=headers)


@router.get("/snapshots/{snapshot_id}/download")
async def download_snapshot_bundle(
    snapshot_id: str,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Keep REST-style download path support while preserving the zip filename contract.
    return await get_snapshot_bundle(snapshot_id=snapshot_id, request=request, principal=principal, db=db)
