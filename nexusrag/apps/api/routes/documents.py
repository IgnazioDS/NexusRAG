from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import get_db, get_tenant_id
from nexusrag.persistence.repos import corpora as corpora_repo
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.services.ingestion import ingest_document


router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    corpus_id: str
    filename: str
    content_type: str
    source: str
    status: str
    error_message: str | None
    created_at: str
    updated_at: str


class DocumentAccepted(BaseModel):
    document_id: str
    status: str


def _to_response(doc) -> DocumentResponse:
    # Serialize datetimes to ISO 8601 for API clients.
    return DocumentResponse(
        id=doc.id,
        tenant_id=doc.tenant_id,
        corpus_id=doc.corpus_id,
        filename=doc.filename,
        content_type=doc.content_type,
        source=doc.source,
        status=doc.status,
        error_message=doc.error_message,
        created_at=doc.created_at.isoformat(),
        updated_at=doc.updated_at.isoformat(),
    )


def _parse_text(upload: UploadFile, body: bytes) -> str:
    # Accept text/plain, text/markdown, or JSON bodies with a text field.
    content_type = (upload.content_type or "").lower()
    if content_type in {"text/plain", "text/markdown"}:
        return body.decode("utf-8", errors="ignore")
    if content_type == "application/json":
        payload = json.loads(body.decode("utf-8", errors="ignore"))
        if not isinstance(payload, dict) or "text" not in payload:
            raise HTTPException(status_code=422, detail="JSON body must include text")
        return str(payload["text"])
    raise HTTPException(status_code=415, detail="Unsupported content type")


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
    document_id = str(uuid4())

    try:
        await documents_repo.create_document(
            db,
            document_id=document_id,
            tenant_id=tenant_id,
            corpus_id=corpus_id,
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            source="upload",
            status="queued",
        )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error while creating document") from exc

    # Schedule ingestion in the background for dev-friendly processing.
    background_tasks.add_task(ingest_document, document_id, text)
    return DocumentAccepted(document_id=document_id, status="queued")


@router.get("")
async def list_documents(
    tenant_id: str = Depends(get_tenant_id),
    corpus_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    try:
        docs = await documents_repo.list_documents(db, tenant_id, corpus_id)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database error while listing documents") from exc
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
        raise HTTPException(status_code=500, detail="Database error while fetching document") from exc
    if doc is None:
        # Use 404 to avoid leaking cross-tenant document existence.
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(doc)
