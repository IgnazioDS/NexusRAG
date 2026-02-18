from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import (
    Principal,
    get_db,
    idempotency_key_header,
    reject_tenant_id_in_body,
    require_role,
)
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Chunk, Document, DocumentLabel, DocumentPermission
from nexusrag.ingestion.chunking import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS
from nexusrag.persistence.repos import corpora as corpora_repo
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.services.ingest.ingestion import write_text_to_storage
from nexusrag.services.ingest.queue import IngestionJobPayload, enqueue_ingestion_job
from nexusrag.core.errors import ServiceBusyError
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.costs.budget_guardrails import cost_headers, evaluate_budget_guardrail
from nexusrag.services.costs.metering import estimate_cost, estimate_tokens, record_cost_event
from nexusrag.apps.api.response import SuccessEnvelope, is_versioned_request, success_response
from nexusrag.services.authz.abac import (
    authorize_document_action,
    authorize_document_create,
    filter_documents_for_principal,
)
from nexusrag.services.entitlements import (
    FEATURE_COST_CONTROLS,
    FEATURE_COST_VISIBILITY,
    get_effective_entitlements,
)
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)
from nexusrag.services.rollouts import resolve_kill_switch
from nexusrag.services.sla.evaluator import evaluate_tenant_sla
from nexusrag.services.sla.signals import record_sla_observation
from nexusrag.services.telemetry import increment_counter
from nexusrag.services.governance import (
    LEGAL_HOLD_SCOPE_DOCUMENT,
    enforce_no_legal_hold,
    enforce_policy,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"], responses=DEFAULT_ERROR_RESPONSES)


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    corpus_id: str
    filename: str
    content_type: str
    source: str
    ingest_source: str
    status: str
    failure_reason: str | None
    created_at: str
    updated_at: str
    queued_at: str | None
    processing_started_at: str | None
    completed_at: str | None
    last_reindexed_at: str | None
    last_job_id: str | None
    num_chunks: int | None = None


class DocumentAccepted(BaseModel):
    document_id: str
    status: str
    job_id: str | None
    status_url: str


class TextIngestRequest(BaseModel):
    corpus_id: str
    text: str
    document_id: str | None = None
    filename: str | None = None
    metadata_json: dict | None = None
    chunk_size_chars: int | None = Field(default=None, ge=1)
    chunk_overlap_chars: int | None = Field(default=None, ge=0)
    overwrite: bool = False

    # Reject unknown fields so tenant_id cannot be supplied in the payload.
    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "corpus_id": "corpus_abc",
                    "text": "Quarterly planning notes and action items...",
                    "filename": "q1_notes.txt",
                    "metadata_json": {"source": "internal", "department": "product"},
                    "chunk_size_chars": 1000,
                    "chunk_overlap_chars": 100,
                    "overwrite": False,
                }
            ]
        },
    }


class ReindexRequest(BaseModel):
    chunk_size_chars: int | None = Field(default=None, ge=1)
    chunk_overlap_chars: int | None = Field(default=None, ge=0)

    # Reject unknown fields so tenant_id cannot be supplied in the payload.
    model_config = {"extra": "forbid"}


def _to_response(doc, *, num_chunks: int | None = None) -> DocumentResponse:
    # Serialize datetimes to ISO 8601 for API clients.
    failure_reason = doc.failure_reason or doc.error_message
    return DocumentResponse(
        id=doc.id,
        tenant_id=doc.tenant_id,
        corpus_id=doc.corpus_id,
        filename=doc.filename,
        content_type=doc.content_type,
        source=doc.source,
        ingest_source=doc.ingest_source,
        status=doc.status,
        failure_reason=failure_reason,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
        queued_at=doc.queued_at.isoformat() if doc.queued_at else None,
        processing_started_at=doc.processing_started_at.isoformat()
        if doc.processing_started_at
        else None,
        completed_at=doc.completed_at.isoformat() if doc.completed_at else None,
        last_reindexed_at=doc.last_reindexed_at.isoformat() if doc.last_reindexed_at else None,
        last_job_id=doc.last_job_id,
        num_chunks=num_chunks,
    )


def _error_detail(code: str, message: str) -> dict[str, str]:
    # Use a stable error envelope for client-side handling.
    return {"code": code, "message": message}


async def _ensure_ingest_enabled() -> None:
    # Block ingestion when the kill switch is active.
    if await resolve_kill_switch("kill.ingest"):
        raise HTTPException(
            status_code=503,
            detail=_error_detail("FEATURE_TEMPORARILY_DISABLED", "Ingestion is temporarily disabled"),
        )


def _parse_text(upload: UploadFile, body: bytes) -> str:
    # Accept text/plain, text/markdown, or JSON bodies with a text field.
    content_type = (upload.content_type or "").lower()
    if content_type in {"text/plain", "text/markdown"}:
        return body.decode("utf-8", errors="ignore")
    if content_type == "application/json":
        payload = json.loads(body.decode("utf-8", errors="ignore"))
        if not isinstance(payload, dict) or "text" not in payload:
            raise HTTPException(
                status_code=422,
                detail=_error_detail(
                    "INGEST_VALIDATION_ERROR",
                    "JSON body must include text",
                ),
            )
        return str(payload["text"])
    raise HTTPException(status_code=415, detail="Unsupported content type")


def _validate_text_payload(text: str) -> None:
    # Reject empty text early to avoid storing empty documents.
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail=_error_detail("INGEST_VALIDATION_ERROR", "Text must not be empty"),
        )


def _resolve_chunk_params(payload: ReindexRequest | TextIngestRequest | None) -> tuple[int, int]:
    chunk_size = payload.chunk_size_chars if payload else None
    chunk_overlap = payload.chunk_overlap_chars if payload else None
    chunk_size = chunk_size or CHUNK_SIZE_CHARS
    chunk_overlap = chunk_overlap or CHUNK_OVERLAP_CHARS
    # Defer overlap validation to ingestion so async failures surface consistently.
    return chunk_size, chunk_overlap


def _utc_now() -> datetime:
    # Use UTC timestamps to keep status fields deterministic across hosts.
    return datetime.now(timezone.utc)


def _status_url(document_id: str, request: Request | None = None) -> str:
    # Provide a stable polling URL for queued ingestion requests.
    prefix = "/v1" if request is not None and is_versioned_request(request) else ""
    return f"{prefix}/documents/{document_id}"


def _sla_headers(*, policy_id: str | None, status_value: str, decision: str, route_class: str, window_end: datetime | None) -> dict[str, str]:
    # Emit stable SLA headers for ingestion and reindex admission decisions.
    return {
        "X-SLA-Status": status_value,
        "X-SLA-Policy-Id": policy_id or "",
        "X-SLA-Decision": decision,
        "X-SLA-Route-Class": route_class,
        "X-SLA-Window-End": window_end.isoformat() if window_end else "",
    }


async def _record_sla_observation_safe(
    *,
    session: AsyncSession,
    tenant_id: str,
    route_class: str,
    latency_ms: float,
    status_code: int,
) -> None:
    # Persist ingestion SLA telemetry best-effort without blocking write paths.
    if not get_settings().sla_engine_enabled:
        return
    try:
        await record_sla_observation(
            session=session,
            tenant_id=tenant_id,
            route_class=route_class,
            latency_ms=latency_ms,
            status_code=status_code,
            saturation_pct=None,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - SLA telemetry is advisory
        await session.rollback()
        logger.warning("sla_observation_write_failed tenant=%s route_class=%s", tenant_id, route_class, exc_info=exc)


async def _evaluate_sla_ingest(
    *,
    session: AsyncSession,
    principal: Principal,
    request: Request,
    request_id: str,
    route_class: str = "ingest",
) -> dict[str, str]:
    # Enforce tenant SLA admission decisions for ingest/reindex operations.
    decision = await evaluate_tenant_sla(
        session=session,
        tenant_id=principal.tenant_id,
        route_class=route_class,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        request=request,
        request_id=request_id,
    )
    headers = _sla_headers(
        policy_id=decision.policy_id,
        status_value=decision.status,
        decision=decision.enforcement_decision,
        route_class=route_class,
        window_end=decision.window_end,
    )
    if decision.enforcement_decision == "shed":
        await record_event(
            session=session,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="sla.enforcement.shed",
            outcome="failure",
            resource_type=route_class,
            resource_id=request_id,
            request_id=request_id,
            metadata={"policy_id": decision.policy_id},
            commit=True,
            best_effort=True,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SLA_SHED_LOAD",
                "message": "Request shed due to sustained SLA breach",
            },
            headers=headers,
        )
    if decision.enforcement_decision == "warn":
        await record_event(
            session=session,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="sla.enforcement.warned",
            outcome="success",
            resource_type=route_class,
            resource_id=request_id,
            request_id=request_id,
            metadata={"policy_id": decision.policy_id},
            commit=True,
            best_effort=True,
        )
    if decision.enforcement_decision == "degrade":
        await record_event(
            session=session,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="sla.enforcement.degraded",
            outcome="success",
            resource_type=route_class,
            resource_id=request_id,
            request_id=request_id,
            metadata={"policy_id": decision.policy_id},
            commit=True,
            best_effort=True,
        )
    return headers


async def _resolve_cost_entitlements(
    *,
    session: AsyncSession,
    tenant_id: str,
) -> tuple[bool, bool]:
    # Resolve cost entitlements once per request to avoid redundant lookups.
    entitlements = await get_effective_entitlements(session, tenant_id)
    controls_enabled = bool(
        entitlements.get(FEATURE_COST_CONTROLS, None)
        and entitlements[FEATURE_COST_CONTROLS].enabled
    )
    visibility_enabled = bool(
        entitlements.get(FEATURE_COST_VISIBILITY, None)
        and entitlements[FEATURE_COST_VISIBILITY].enabled
    )
    return controls_enabled, visibility_enabled


async def _estimate_ingest_cost(
    *,
    session: AsyncSession,
    settings,
    text: str,
    byte_count: int,
    chunk_size: int,
    tokens_override: int | None = None,
) -> tuple[Decimal, bool, dict[str, int]]:
    # Compute deterministic ingest estimates for budget guardrails.
    ratio = settings.cost_estimator_token_chars_ratio or 4.0
    tokens = tokens_override if tokens_override is not None else estimate_tokens(text, ratio=ratio)
    embedding = await estimate_cost(
        session=session,
        provider="internal",
        component="embedding",
        rate_type="per_1k_tokens",
        units={"tokens": tokens, "chunk_size": chunk_size},
    )
    storage = await estimate_cost(
        session=session,
        provider="internal",
        component="storage",
        rate_type="per_mb",
        units={"bytes": byte_count},
    )
    queue = await estimate_cost(
        session=session,
        provider="internal",
        component="queue",
        rate_type="per_request",
        units={"requests": 1},
    )
    total = embedding.cost_usd + storage.cost_usd + queue.cost_usd
    return total, True, {"tokens": tokens, "bytes": byte_count}


async def _ensure_owner_permission(
    *,
    session: AsyncSession,
    principal: Principal,
    document_id: str,
) -> None:
    # Grant owner-level access to document creators for future ACL checks.
    result = await session.execute(
        select(DocumentPermission).where(
            DocumentPermission.tenant_id == principal.tenant_id,
            DocumentPermission.document_id == document_id,
            DocumentPermission.principal_type == "user",
            DocumentPermission.principal_id == principal.subject_id,
            DocumentPermission.permission == "owner",
        )
    )
    if result.scalar_one_or_none() is not None:
        return
    session.add(
        DocumentPermission(
            id=uuid4().hex,
            tenant_id=principal.tenant_id,
            document_id=document_id,
            principal_type="user",
            principal_id=principal.subject_id,
            permission="owner",
            granted_by=principal.api_key_id,
            expires_at=None,
        )
    )


async def _sync_document_labels(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: str,
    labels: dict[str, Any] | None,
) -> None:
    # Align document labels with metadata for ABAC evaluation inputs.
    if labels is None:
        return
    if not isinstance(labels, dict):
        raise HTTPException(
            status_code=422,
            detail=_error_detail("INGEST_VALIDATION_ERROR", "labels must be an object"),
        )
    await session.execute(
        delete(DocumentLabel).where(
            DocumentLabel.tenant_id == tenant_id,
            DocumentLabel.document_id == document_id,
        )
    )
    for key, value in labels.items():
        if key is None:
            continue
        session.add(
            DocumentLabel(
                id=uuid4().hex,
                tenant_id=tenant_id,
                document_id=document_id,
                key=str(key),
                value=str(value),
            )
        )


def _accepted_response(
    document_id: str,
    status: str,
    job_id: str | None,
    request: Request | None = None,
) -> DocumentAccepted:
    # Keep accepted responses consistent across enqueue and idempotent paths.
    return DocumentAccepted(
        document_id=document_id,
        status=status,
        job_id=job_id,
        status_url=_status_url(document_id, request),
    )


async def _enqueue_or_fail(
    db: AsyncSession,
    document_id: str,
    payload: IngestionJobPayload,
) -> None:
    # Update the document to failed if Redis is unavailable.
    try:
        await enqueue_ingestion_job(payload)
    except ServiceBusyError as exc:
        await documents_repo.update_status(
            db,
            document_id,
            status="failed",
            error_message="Ingestion service busy",
            failure_reason="Ingestion service busy",
            completed_at=_utc_now(),
            last_job_id=payload.request_id,
        )
        await db.commit()
        increment_counter("service_busy_total")
        raise HTTPException(
            status_code=503,
            detail=_error_detail("SERVICE_BUSY", "Ingestion service busy; retry later"),
            headers={"Retry-After": "1"},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - map queue failures to a 503 response
        await documents_repo.update_status(
            db,
            document_id,
            status="failed",
            error_message="Ingestion queue unavailable",
            failure_reason="Ingestion queue unavailable",
            completed_at=_utc_now(),
            last_job_id=payload.request_id,
        )
        await db.commit()
        logger.exception("Failed to enqueue ingestion job for %s", document_id)
        raise HTTPException(
            status_code=503,
            detail=_error_detail("QUEUE_ERROR", "Ingestion queue unavailable"),
        ) from exc


# Accept legacy unwrapped responses; v1 routes are wrapped by middleware.
@router.post("", status_code=202, response_model=SuccessEnvelope[DocumentAccepted] | DocumentAccepted)
async def upload_document(
    request: Request,
    response: Response,
    corpus_id: str = Form(...),
    file: UploadFile = File(...),
    document_id: str | None = Form(default=None),
    overwrite: bool = Form(default=False),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
) -> DocumentAccepted:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    route_started = time.monotonic()
    await _ensure_ingest_enabled()
    tenant_id = principal.tenant_id
    # Enforce tenant scoping to avoid cross-tenant corpus access.
    corpus = await corpora_repo.get_by_tenant_and_id(db, tenant_id, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus not found")

    body = await file.read()
    request_hash = compute_request_hash(
        {
            "corpus_id": corpus_id,
            "document_id": document_id,
            "filename": file.filename or "upload",
            "content_type": file.content_type or "application/octet-stream",
            "overwrite": overwrite,
            "file_sha256": hashlib.sha256(body).hexdigest(),
        }
    )
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    existing = None
    if document_id:
        existing = await documents_repo.get_document(db, tenant_id, document_id)
        if existing is None:
            # Avoid leaking cross-tenant IDs by returning 404 on mismatch.
            other = await documents_repo.get_document_by_id(db, document_id)
            if other is not None:
                raise HTTPException(status_code=404, detail="Document not found")
        else:
            # Enforce ABAC + ACL before mutating existing documents.
            await authorize_document_action(
                session=db,
                principal=principal,
                document=existing,
                action="write",
                request=request,
            )
            if existing.corpus_id != corpus_id:
                raise HTTPException(status_code=409, detail="Document belongs to a different corpus")
            if existing.status in {"queued", "processing"}:
                response.status_code = 200
                accepted = _accepted_response(
                    existing.id,
                    existing.status,
                    existing.last_job_id,
                    request,
                )
                payload = success_response(request=request, data=accepted)
                await store_idempotency_response(
                    db=db,
                    context=idempotency_ctx,
                    response_status=response.status_code,
                    response_body=jsonable_encoder(payload),
                )
                return payload
            if existing.status in {"succeeded", "failed"} and not overwrite:
                response.status_code = 200
                accepted = _accepted_response(
                    existing.id,
                    existing.status,
                    existing.last_job_id,
                    request,
                )
                payload = success_response(request=request, data=accepted)
                await store_idempotency_response(
                    db=db,
                    context=idempotency_ctx,
                    response_status=response.status_code,
                    response_body=jsonable_encoder(payload),
                )
                return payload

    if existing is None:
        # Enforce ABAC policy for new document creation within the corpus.
        await authorize_document_create(
            session=db,
            principal=principal,
            corpus_id=corpus_id,
            labels=None,
            request=request,
        )
    text = _parse_text(file, body)
    _validate_text_payload(text)
    request_id = str(uuid4())
    # Enforce SLA admission decisions before budget checks and enqueue work.
    response.headers.update(
        await _evaluate_sla_ingest(
            session=db,
            principal=principal,
            request=request,
            request_id=request_id,
            route_class="ingest",
        )
    )
    # Apply budget guardrails before writing content to storage or queueing work.
    cost_controls_enabled, cost_visibility_enabled = await _resolve_cost_entitlements(
        session=db,
        tenant_id=tenant_id,
    )
    if cost_controls_enabled or cost_visibility_enabled:
        projected_cost, estimated, _estimate_meta = await _estimate_ingest_cost(
            session=db,
            settings=get_settings(),
            text=text,
            byte_count=len(body),
            chunk_size=CHUNK_SIZE_CHARS,
        )
        decision = await evaluate_budget_guardrail(
            session=db,
            tenant_id=tenant_id,
            projected_cost_usd=projected_cost,
            estimated=estimated,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            route_class="ingest",
            request_id=request_id,
            request=request,
            operation="ingest",
            enforce=cost_controls_enabled,
            raise_on_block=True,
        )
        if cost_visibility_enabled:
            response.headers.update(cost_headers(decision))
    document_id = document_id or str(uuid4())
    storage_path = write_text_to_storage(document_id, text)
    queued_at = _utc_now()

    try:
        if existing is not None:
            # Overwrite updates existing document metadata and requeues ingestion.
            existing.filename = file.filename or "upload"
            existing.content_type = file.content_type or "application/octet-stream"
            existing.ingest_source = "upload_file"
            existing.source = "upload_file"
            existing.storage_path = storage_path
            existing.metadata_json = {}
            existing.status = "queued"
            existing.error_message = None
            existing.failure_reason = None
            existing.queued_at = queued_at
            existing.processing_started_at = None
            existing.completed_at = None
            existing.last_job_id = request_id
        else:
            await documents_repo.create_document(
                db,
                document_id=document_id,
                tenant_id=tenant_id,
                corpus_id=corpus_id,
                filename=file.filename or "upload",
                content_type=file.content_type or "application/octet-stream",
                ingest_source="upload_file",
                storage_path=storage_path,
                metadata_json={},
                status="queued",
                queued_at=queued_at,
                last_job_id=request_id,
            )
            await _ensure_owner_permission(
                session=db,
                principal=principal,
                document_id=document_id,
            )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while creating document"),
        ) from exc

    payload = IngestionJobPayload(
        tenant_id=tenant_id,
        corpus_id=corpus_id,
        document_id=document_id,
        ingest_source="upload_file",
        storage_path=storage_path,
        raw_text=None,
        filename=file.filename or "upload",
        metadata_json={},
        chunk_size_chars=CHUNK_SIZE_CHARS,
        chunk_overlap_chars=CHUNK_OVERLAP_CHARS,
        request_id=request_id,
    )
    await _enqueue_or_fail(db, document_id, payload)
    # Record storage + queue costs after enqueue; failures should not block ingestion.
    try:
        await record_cost_event(
            session=db,
            tenant_id=tenant_id,
            request_id=request_id,
            session_id=None,
            route_class="ingest",
            component="storage",
            provider="internal",
            units={"bytes": len(body)},
            rate_type="per_mb",
            metadata={"estimated": True},
        )
        await record_cost_event(
            session=db,
            tenant_id=tenant_id,
            request_id=request_id,
            session_id=None,
            route_class="ingest",
            component="queue",
            provider="internal",
            units={"requests": 1},
            rate_type="per_request",
            metadata={"estimated": True},
        )
    except Exception as exc:  # noqa: BLE001 - best-effort metering should not block ingestion
        logger.warning("cost_metering_ingest_failed request_id=%s", request_id, exc_info=exc)
    request_ctx = get_request_context(request)
    # Record queued ingestion only after the enqueue succeeds.
    await record_event(
        session=db,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="documents.ingest.enqueued",
        outcome="success",
        resource_type="document",
        resource_id=document_id,
        request_id=request_id,
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "corpus_id": corpus_id,
            "ingest_source": "upload_file",
            "file_name": file.filename or "upload",
            "file_mime": file.content_type or "application/octet-stream",
            "byte_count": len(body),
            "overwrite": overwrite,
        },
        commit=True,
        best_effort=True,
    )
    accepted = _accepted_response(document_id, "queued", request_id, request)
    payload = success_response(request=request, data=accepted)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        # Persist explicit accepted status; FastAPI may not hydrate response.status_code yet.
        response_status=202,
        response_body=jsonable_encoder(payload),
    )
    await _record_sla_observation_safe(
        session=db,
        tenant_id=tenant_id,
        route_class="ingest",
        latency_ms=(time.monotonic() - route_started) * 1000.0,
        status_code=202,
    )
    return payload


@router.post("/text", status_code=202, response_model=SuccessEnvelope[DocumentAccepted] | DocumentAccepted)
async def ingest_text_document(
    request: Request,
    payload: TextIngestRequest,
    response: Response,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
) -> DocumentAccepted:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    route_started = time.monotonic()
    await _ensure_ingest_enabled()
    tenant_id = principal.tenant_id
    _validate_text_payload(payload.text)
    metadata_json = payload.metadata_json or {}
    if not isinstance(metadata_json, dict):
        raise HTTPException(
            status_code=422,
            detail=_error_detail(
                "INGEST_VALIDATION_ERROR",
                "metadata_json must be an object when provided",
            ),
        )
    labels_present = "labels" in metadata_json
    labels_payload = metadata_json.get("labels") if labels_present else None
    if labels_present and labels_payload is None:
        raise HTTPException(
            status_code=422,
            detail=_error_detail("INGEST_VALIDATION_ERROR", "labels must be an object"),
        )
    request_hash = compute_request_hash(payload.model_dump())
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    corpus = await corpora_repo.get_by_tenant_and_id(db, tenant_id, payload.corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus not found")

    existing = None
    if payload.document_id:
        existing = await documents_repo.get_document(db, tenant_id, payload.document_id)
        if existing is None:
            # Avoid leaking cross-tenant IDs by returning 404 on mismatch.
            other = await documents_repo.get_document_by_id(db, payload.document_id)
            if other is not None:
                raise HTTPException(status_code=404, detail="Document not found")
        else:
            # Enforce ABAC + ACL before mutating existing documents.
            await authorize_document_action(
                session=db,
                principal=principal,
                document=existing,
                action="write",
                request=request,
            )
            if existing.corpus_id != payload.corpus_id:
                raise HTTPException(status_code=409, detail="Document belongs to a different corpus")
            if existing.status in {"queued", "processing"}:
                response.status_code = 200
                accepted = _accepted_response(
                    existing.id,
                    existing.status,
                    existing.last_job_id,
                    request,
                )
                payload_body = success_response(request=request, data=accepted)
                await store_idempotency_response(
                    db=db,
                    context=idempotency_ctx,
                    response_status=response.status_code,
                    response_body=jsonable_encoder(payload_body),
                )
                return payload_body
            if existing.status in {"succeeded", "failed"} and not payload.overwrite:
                response.status_code = 200
                accepted = _accepted_response(
                    existing.id,
                    existing.status,
                    existing.last_job_id,
                    request,
                )
                payload_body = success_response(request=request, data=accepted)
                await store_idempotency_response(
                    db=db,
                    context=idempotency_ctx,
                    response_status=response.status_code,
                    response_body=jsonable_encoder(payload_body),
                )
                return payload_body

    if existing is None:
        # Enforce ABAC policy for new document creation within the corpus.
        await authorize_document_create(
            session=db,
            principal=principal,
            corpus_id=payload.corpus_id,
            labels=(metadata_json.get("labels") if isinstance(metadata_json, dict) else None),
            request=request,
        )
    document_id = payload.document_id or str(uuid4())
    chunk_size, chunk_overlap = _resolve_chunk_params(payload)
    request_id = str(uuid4())
    # Enforce SLA admission decisions before budget checks and enqueue work.
    response.headers.update(
        await _evaluate_sla_ingest(
            session=db,
            principal=principal,
            request=request,
            request_id=request_id,
            route_class="ingest",
        )
    )
    # Apply budget guardrails before storage writes and ingestion queueing.
    byte_count = len(payload.text.encode("utf-8"))
    cost_controls_enabled, cost_visibility_enabled = await _resolve_cost_entitlements(
        session=db,
        tenant_id=tenant_id,
    )
    if cost_controls_enabled or cost_visibility_enabled:
        projected_cost, estimated, _estimate_meta = await _estimate_ingest_cost(
            session=db,
            settings=get_settings(),
            text=payload.text,
            byte_count=byte_count,
            chunk_size=chunk_size,
        )
        decision = await evaluate_budget_guardrail(
            session=db,
            tenant_id=tenant_id,
            projected_cost_usd=projected_cost,
            estimated=estimated,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            route_class="ingest",
            request_id=request_id,
            request=request,
            operation="ingest",
            enforce=cost_controls_enabled,
            raise_on_block=True,
        )
        if cost_visibility_enabled:
            response.headers.update(cost_headers(decision))
    storage_path = write_text_to_storage(document_id, payload.text)
    queued_at = _utc_now()

    try:
        if existing is not None:
            # Overwrite updates existing document metadata and requeues ingestion.
            existing.filename = payload.filename or "raw_text.txt"
            existing.content_type = "text/plain"
            existing.ingest_source = "raw_text"
            existing.source = "raw_text"
            existing.storage_path = storage_path
            existing.metadata_json = metadata_json
            existing.status = "queued"
            existing.error_message = None
            existing.failure_reason = None
            existing.queued_at = queued_at
            existing.processing_started_at = None
            existing.completed_at = None
            existing.last_job_id = request_id
            if labels_present:
                await _sync_document_labels(
                    session=db,
                    tenant_id=tenant_id,
                    document_id=existing.id,
                    labels=labels_payload,
                )
        else:
            await documents_repo.create_document(
                db,
                document_id=document_id,
                tenant_id=tenant_id,
                corpus_id=payload.corpus_id,
                filename=payload.filename or "raw_text.txt",
                content_type="text/plain",
                ingest_source="raw_text",
                storage_path=storage_path,
                metadata_json=metadata_json,
                status="queued",
                queued_at=queued_at,
                last_job_id=request_id,
            )
            await _ensure_owner_permission(
                session=db,
                principal=principal,
                document_id=document_id,
            )
            if labels_present:
                await _sync_document_labels(
                    session=db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    labels=labels_payload,
                )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while creating document"),
        ) from exc

    ingest_payload = IngestionJobPayload(
        tenant_id=tenant_id,
        corpus_id=payload.corpus_id,
        document_id=document_id,
        ingest_source="raw_text",
        storage_path=storage_path,
        raw_text=payload.text,
        filename=payload.filename or "raw_text.txt",
        metadata_json=metadata_json,
        chunk_size_chars=chunk_size,
        chunk_overlap_chars=chunk_overlap,
        request_id=request_id,
    )
    await _enqueue_or_fail(db, document_id, ingest_payload)
    # Record storage + queue costs after enqueue; failures should not block ingestion.
    try:
        await record_cost_event(
            session=db,
            tenant_id=tenant_id,
            request_id=request_id,
            session_id=None,
            route_class="ingest",
            component="storage",
            provider="internal",
            units={"bytes": byte_count},
            rate_type="per_mb",
            metadata={"estimated": True},
        )
        await record_cost_event(
            session=db,
            tenant_id=tenant_id,
            request_id=request_id,
            session_id=None,
            route_class="ingest",
            component="queue",
            provider="internal",
            units={"requests": 1},
            rate_type="per_request",
            metadata={"estimated": True},
        )
    except Exception as exc:  # noqa: BLE001 - best-effort metering should not block ingestion
        logger.warning("cost_metering_ingest_failed request_id=%s", request_id, exc_info=exc)
    request_ctx = get_request_context(request)
    # Record queued ingestion only after the enqueue succeeds.
    await record_event(
        session=db,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="documents.ingest.enqueued",
        outcome="success",
        resource_type="document",
        resource_id=document_id,
        request_id=request_id,
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "corpus_id": payload.corpus_id,
            "ingest_source": "raw_text",
            "file_name": payload.filename or "raw_text.txt",
            "char_count": len(payload.text),
            "metadata_keys": sorted(metadata_json.keys()),
            "overwrite": payload.overwrite,
        },
        commit=True,
        best_effort=True,
    )
    accepted = _accepted_response(document_id, "queued", request_id, request)
    payload_body = success_response(request=request, data=accepted)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        # Persist explicit accepted status; FastAPI may not hydrate response.status_code yet.
        response_status=202,
        response_body=jsonable_encoder(payload_body),
    )
    await _record_sla_observation_safe(
        session=db,
        tenant_id=tenant_id,
        route_class="ingest",
        latency_ms=(time.monotonic() - route_started) * 1000.0,
        status_code=202,
    )
    return payload_body


@router.get("", response_model=SuccessEnvelope[list[DocumentResponse]] | list[DocumentResponse])
async def list_documents(
    request: Request,
    principal: Principal = Depends(require_role("reader")),
    corpus_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    tenant_id = principal.tenant_id
    try:
        docs = await documents_repo.list_documents(db, tenant_id, corpus_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while listing documents"),
        ) from exc
    # Filter documents through ABAC + ACL to avoid leaking unauthorized resources.
    docs = await filter_documents_for_principal(
        session=db,
        principal=principal,
        documents=docs,
        action="read",
        request=request,
    )
    return [_to_response(doc) for doc in docs]


@router.get("/{document_id}", response_model=SuccessEnvelope[DocumentResponse] | DocumentResponse)
async def get_document(
    document_id: str,
    request: Request,
    principal: Principal = Depends(require_role("reader")),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    tenant_id = principal.tenant_id
    try:
        doc = await documents_repo.get_document(db, tenant_id, document_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while fetching document"),
        ) from exc
    if doc is None:
        # Use 404 to avoid leaking cross-tenant document existence.
        raise HTTPException(status_code=404, detail="Document not found")
    # Enforce ABAC + ACL before returning document metadata.
    await authorize_document_action(
        session=db,
        principal=principal,
        document=doc,
        action="read",
        request=request,
    )
    num_chunks = None
    if doc.status == "succeeded":
        try:
            num_chunks = await documents_repo.count_chunks(db, doc.id)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=500,
                detail=_error_detail("DB_ERROR", "Database error while counting chunks"),
            ) from exc
    return _to_response(doc, num_chunks=num_chunks)


@router.post(
    "/{document_id}/reindex",
    status_code=202,
    response_model=SuccessEnvelope[DocumentAccepted] | DocumentAccepted,
)
async def reindex_document(
    document_id: str,
    request: Request,
    response: Response,
    payload: ReindexRequest | None = None,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
) -> DocumentAccepted:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    route_started = time.monotonic()
    await _ensure_ingest_enabled()
    tenant_id = principal.tenant_id
    request_ctx = get_request_context(request)
    decision = await enforce_policy(
        session=db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        rule_key="documents.reindex",
        context={
            "endpoint": request.url.path,
            "method": request.method,
            "resource_type": "document",
            "document_id": document_id,
            "actor_role": principal.role,
        },
        request_id=request_ctx["request_id"],
    )
    if decision.force_legal_hold_check:
        await enforce_no_legal_hold(
            db,
            tenant_id=tenant_id,
            scope_type=LEGAL_HOLD_SCOPE_DOCUMENT,
            scope_id=document_id,
        )
    try:
        doc = await documents_repo.get_document(db, tenant_id, document_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while fetching document"),
        ) from exc
    if doc is None:
        # Tenant mismatch returns 404 to avoid leaking document existence.
        raise HTTPException(status_code=404, detail="Document not found")
    # Enforce ABAC + ACL before reindexing document content.
    await authorize_document_action(
        session=db,
        principal=principal,
        document=doc,
        action="reindex",
        request=request,
    )
    if doc.status in {"queued", "processing"}:
        raise HTTPException(
            status_code=409,
            detail=_error_detail(
                "INGEST_IN_PROGRESS", "Document ingestion is already in progress"
            ),
        )
    if not doc.storage_path:
        raise HTTPException(
            status_code=409,
            detail=_error_detail(
                "INGEST_SOURCE_MISSING",
                "Document source text is not available for reindexing",
            ),
        )

    request_hash = compute_request_hash(
        {"document_id": document_id, "params": payload.model_dump() if payload else {}}
    )
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    chunk_size, chunk_overlap = _resolve_chunk_params(payload)
    request_id = str(uuid4())
    # Enforce SLA admission decisions before budget checks and queueing.
    response.headers.update(
        await _evaluate_sla_ingest(
            session=db,
            principal=principal,
            request=request,
            request_id=request_id,
            route_class="ingest",
        )
    )
    # Apply budget guardrails before reindexing to prevent cap overruns.
    cost_controls_enabled, cost_visibility_enabled = await _resolve_cost_entitlements(
        session=db,
        tenant_id=tenant_id,
    )
    if cost_controls_enabled or cost_visibility_enabled:
        byte_count = 0
        if doc.storage_path:
            try:
                byte_count = Path(doc.storage_path).stat().st_size
            except OSError:
                byte_count = 0
        ratio = get_settings().cost_estimator_token_chars_ratio or 4.0
        tokens_override = max(1, int(byte_count / ratio)) if byte_count else 0
        projected_cost, estimated, _estimate_meta = await _estimate_ingest_cost(
            session=db,
            settings=get_settings(),
            text="",
            byte_count=byte_count,
            chunk_size=chunk_size,
            tokens_override=tokens_override,
        )
        decision = await evaluate_budget_guardrail(
            session=db,
            tenant_id=tenant_id,
            projected_cost_usd=projected_cost,
            estimated=estimated,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            route_class="ingest",
            request_id=request_id,
            request=request,
            operation="reindex",
            enforce=cost_controls_enabled,
            raise_on_block=True,
        )
        if cost_visibility_enabled:
            response.headers.update(cost_headers(decision))
    queued_at = _utc_now()

    try:
        # Reindex queues a new job and resets status fields for polling.
        doc.status = "queued"
        doc.error_message = None
        doc.failure_reason = None
        doc.queued_at = queued_at
        doc.processing_started_at = None
        doc.completed_at = None
        doc.last_job_id = request_id
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while updating document"),
        ) from exc

    ingest_payload = IngestionJobPayload(
        tenant_id=tenant_id,
        corpus_id=doc.corpus_id,
        document_id=document_id,
        ingest_source=doc.ingest_source,
        storage_path=doc.storage_path,
        raw_text=None,
        filename=doc.filename,
        metadata_json=doc.metadata_json,
        chunk_size_chars=chunk_size,
        chunk_overlap_chars=chunk_overlap,
        request_id=request_id,
        is_reindex=True,
    )
    await _enqueue_or_fail(db, document_id, ingest_payload)
    # Record queue costs for reindex jobs; failures should not block ingestion.
    try:
        await record_cost_event(
            session=db,
            tenant_id=tenant_id,
            request_id=request_id,
            session_id=None,
            route_class="ingest",
            component="queue",
            provider="internal",
            units={"requests": 1},
            rate_type="per_request",
            metadata={"estimated": True, "reindex": True},
        )
    except Exception as exc:  # noqa: BLE001 - best-effort metering should not block ingestion
        logger.warning("cost_metering_ingest_failed request_id=%s", request_id, exc_info=exc)
    # Record queued reindex only after the enqueue succeeds.
    await record_event(
        session=db,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="documents.reindex.enqueued",
        outcome="success",
        resource_type="document",
        resource_id=document_id,
        request_id=request_id,
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "corpus_id": doc.corpus_id,
            "ingest_source": doc.ingest_source,
            "chunk_size_chars": chunk_size,
            "chunk_overlap_chars": chunk_overlap,
        },
        commit=True,
        best_effort=True,
    )
    accepted = _accepted_response(document_id, "queued", request_id, request)
    payload_body = success_response(request=request, data=accepted)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=202,
        response_body=jsonable_encoder(payload_body),
    )
    await _record_sla_observation_safe(
        session=db,
        tenant_id=tenant_id,
        route_class="ingest",
        latency_ms=(time.monotonic() - route_started) * 1000.0,
        status_code=202,
    )
    return payload_body


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    request: Request,
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    tenant_id = principal.tenant_id
    request_ctx = get_request_context(request)
    await enforce_policy(
        session=db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        rule_key="documents.delete",
        context={
            "endpoint": request.url.path,
            "method": request.method,
            "resource_type": "document",
            "document_id": document_id,
            "actor_role": principal.role,
        },
        request_id=request_ctx["request_id"],
    )
    await enforce_no_legal_hold(
        db,
        tenant_id=tenant_id,
        scope_type=LEGAL_HOLD_SCOPE_DOCUMENT,
        scope_id=document_id,
    )
    try:
        doc = await documents_repo.get_document(db, tenant_id, document_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while fetching document"),
        ) from exc
    if doc is None:
        # Tenant mismatch returns 404 to avoid leaking document existence.
        raise HTTPException(status_code=404, detail="Document not found")
    # Enforce ABAC + ACL before deleting document content.
    await authorize_document_action(
        session=db,
        principal=principal,
        document=doc,
        action="delete",
        request=request,
    )
    if doc.status in {"queued", "processing"}:
        raise HTTPException(
            status_code=409,
            detail=_error_detail(
                "INGEST_IN_PROGRESS", "Document ingestion is already in progress"
            ),
        )

    request_hash = compute_request_hash({"document_id": document_id})
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)

    storage_path = doc.storage_path

    try:
        await db.execute(delete(DocumentPermission).where(DocumentPermission.document_id == document_id))
        await db.execute(delete(DocumentLabel).where(DocumentLabel.document_id == document_id))
        await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
        await db.execute(delete(Document).where(Document.id == document_id))
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while deleting document"),
        ) from exc

    if storage_path:
        try:
            Path(storage_path).unlink(missing_ok=True)
        except OSError:
            # Deleting local artifacts should not block API responses.
            logger.warning("Failed to remove document storage %s", storage_path)

    # Record deletions after the document and chunks are removed successfully.
    deleted_at = datetime.now(timezone.utc)
    await record_event(
        session=db,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="document.deleted",
        outcome="success",
        resource_type="document",
        resource_id=document_id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "doc_id": document_id,
            "corpus_id": doc.corpus_id,
            "tenant_id": tenant_id,
            "deleted_at": deleted_at.isoformat(),
        },
        commit=False,
        best_effort=True,
    )
    await record_event(
        session=db,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="documents.deleted",
        outcome="success",
        resource_type="document",
        resource_id=document_id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "corpus_id": doc.corpus_id,
            "had_storage": bool(storage_path),
        },
        commit=True,
        best_effort=True,
    )
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=204,
        response_body=None,
    )
    return Response(status_code=204)
