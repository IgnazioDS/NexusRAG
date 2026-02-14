from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
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
from sqlalchemy import delete
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
from nexusrag.domain.models import Chunk, Document
from nexusrag.ingestion.chunking import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS
from nexusrag.persistence.repos import corpora as corpora_repo
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.services.ingest.ingestion import write_text_to_storage
from nexusrag.services.ingest.queue import IngestionJobPayload, enqueue_ingestion_job
from nexusrag.core.errors import ServiceBusyError
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.apps.api.response import SuccessEnvelope, is_versioned_request, success_response
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)
from nexusrag.services.rollouts import resolve_kill_switch
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

    text = _parse_text(file, body)
    _validate_text_payload(text)
    document_id = document_id or str(uuid4())
    storage_path = write_text_to_storage(document_id, text)
    request_id = str(uuid4())
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
        response_status=response.status_code,
        response_body=jsonable_encoder(payload),
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

    document_id = payload.document_id or str(uuid4())
    storage_path = write_text_to_storage(document_id, payload.text)
    request_id = str(uuid4())
    queued_at = _utc_now()
    chunk_size, chunk_overlap = _resolve_chunk_params(payload)

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
        response_status=response.status_code,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body


@router.get("", response_model=SuccessEnvelope[list[DocumentResponse]] | list[DocumentResponse])
async def list_documents(
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
    return [_to_response(doc) for doc in docs]


@router.get("/{document_id}", response_model=SuccessEnvelope[DocumentResponse] | DocumentResponse)
async def get_document(
    document_id: str,
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
    payload: ReindexRequest | None = None,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
) -> DocumentAccepted:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
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
