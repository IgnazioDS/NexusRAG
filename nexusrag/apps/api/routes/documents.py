from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import get_db, get_tenant_id
from nexusrag.domain.models import Chunk, Document
from nexusrag.ingestion.chunking import CHUNK_OVERLAP_CHARS, CHUNK_SIZE_CHARS
from nexusrag.persistence.repos import corpora as corpora_repo
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.services.ingest.ingestion import (
    ingest_document_from_storage,
    write_text_to_storage,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    corpus_id: str
    filename: str
    content_type: str
    source: str
    ingest_source: str
    status: str
    error_message: str | None
    created_at: str
    updated_at: str
    last_reindexed_at: str | None


class DocumentAccepted(BaseModel):
    document_id: str
    status: str


class TextIngestRequest(BaseModel):
    corpus_id: str
    text: str
    document_id: str | None = None
    filename: str | None = None
    metadata_json: dict | None = None


class TextIngestResponse(BaseModel):
    document_id: str
    status: str
    num_chunks: int


class ReindexRequest(BaseModel):
    chunk_size_chars: int | None = Field(default=None, ge=1)
    chunk_overlap_chars: int | None = Field(default=None, ge=0)


class ReindexResponse(BaseModel):
    document_id: str
    status: str
    num_chunks: int


def _to_response(doc) -> DocumentResponse:
    # Serialize datetimes to ISO 8601 for API clients.
    return DocumentResponse(
        id=doc.id,
        tenant_id=doc.tenant_id,
        corpus_id=doc.corpus_id,
        filename=doc.filename,
        content_type=doc.content_type,
        source=doc.source,
        ingest_source=doc.ingest_source,
        status=doc.status,
        error_message=doc.error_message,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
        last_reindexed_at=doc.last_reindexed_at.isoformat() if doc.last_reindexed_at else None,
    )


def _error_detail(code: str, message: str) -> dict[str, str]:
    # Use a stable error envelope for client-side handling.
    return {"code": code, "message": message}


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


def _resolve_chunk_params(payload: ReindexRequest | None) -> tuple[int, int]:
    chunk_size = payload.chunk_size_chars if payload else None
    chunk_overlap = payload.chunk_overlap_chars if payload else None
    chunk_size = chunk_size or CHUNK_SIZE_CHARS
    chunk_overlap = chunk_overlap or CHUNK_OVERLAP_CHARS
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=422,
            detail=_error_detail(
                "INGEST_VALIDATION_ERROR",
                "chunk_overlap_chars must be smaller than chunk_size_chars",
            ),
        )
    return chunk_size, chunk_overlap


async def _run_background_ingest(
    document_id: str,
    storage_path: str,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    # Capture errors so background task failures don't crash the server.
    try:
        await ingest_document_from_storage(
            document_id,
            storage_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            is_reindex=False,
        )
    except Exception:  # noqa: BLE001 - background task errors are logged only
        logger.exception("Background ingestion failed for %s", document_id)


@router.post("", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    corpus_id: str = Form(...),
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentAccepted:
    # Enforce tenant scoping to avoid cross-tenant corpus access.
    corpus = await corpora_repo.get_by_tenant_and_id(db, tenant_id, corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus not found")

    body = await file.read()
    text = _parse_text(file, body)
    _validate_text_payload(text)
    document_id = str(uuid4())
    storage_path = write_text_to_storage(document_id, text)

    try:
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
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while creating document"),
        ) from exc

    # Schedule ingestion in the background for dev-friendly processing.
    background_tasks.add_task(
        _run_background_ingest,
        document_id,
        storage_path,
        CHUNK_SIZE_CHARS,
        CHUNK_OVERLAP_CHARS,
    )
    return DocumentAccepted(document_id=document_id, status="queued")


@router.post("/text", status_code=201)
async def ingest_text_document(
    payload: TextIngestRequest,
    response: Response,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> TextIngestResponse:
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

    corpus = await corpora_repo.get_by_tenant_and_id(db, tenant_id, payload.corpus_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail="Corpus not found")

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
            num_chunks = await documents_repo.count_chunks(db, existing.id)
            response.status_code = 200
            return TextIngestResponse(
                document_id=existing.id,
                status=existing.status,
                num_chunks=num_chunks,
            )

    document_id = payload.document_id or str(uuid4())
    storage_path = write_text_to_storage(document_id, payload.text)

    try:
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
            status="processing",
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while creating document"),
        ) from exc

    try:
        num_chunks = await ingest_document_from_storage(
            document_id,
            storage_path,
            chunk_size=CHUNK_SIZE_CHARS,
            chunk_overlap=CHUNK_OVERLAP_CHARS,
            is_reindex=False,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=409,
            detail=_error_detail("INGEST_SOURCE_MISSING", "Stored document text is missing"),
        )

    return TextIngestResponse(
        document_id=document_id,
        status="succeeded",
        num_chunks=num_chunks,
    )


@router.get("")
async def list_documents(
    tenant_id: str = Depends(get_tenant_id),
    corpus_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    try:
        docs = await documents_repo.list_documents(db, tenant_id, corpus_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=_error_detail("DB_ERROR", "Database error while listing documents"),
        ) from exc
    return [_to_response(doc) for doc in docs]


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
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
    return _to_response(doc)


@router.post("/{document_id}/reindex")
async def reindex_document(
    document_id: str,
    payload: ReindexRequest | None = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ReindexResponse:
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
    if not doc.storage_path:
        raise HTTPException(
            status_code=409,
            detail=_error_detail(
                "INGEST_SOURCE_MISSING",
                "Document source text is not available for reindexing",
            ),
        )

    chunk_size, chunk_overlap = _resolve_chunk_params(payload)

    try:
        num_chunks = await ingest_document_from_storage(
            document_id,
            doc.storage_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            is_reindex=True,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=409,
            detail=_error_detail("INGEST_SOURCE_MISSING", "Stored document text is missing"),
        )

    return ReindexResponse(document_id=document_id, status="succeeded", num_chunks=num_chunks)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
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

    return Response(status_code=204)
