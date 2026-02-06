from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import Chunk, Document


async def create_document(
    session: AsyncSession,
    *,
    document_id: str,
    tenant_id: str,
    corpus_id: str,
    filename: str,
    content_type: str,
    ingest_source: str,
    storage_path: str | None,
    metadata_json: dict,
    status: str,
) -> Document:
    # Create a document row explicitly so status transitions are tracked.
    doc = Document(
        id=document_id,
        tenant_id=tenant_id,
        corpus_id=corpus_id,
        filename=filename,
        content_type=content_type,
        # Keep source aligned with ingest_source for backward compatibility.
        source=ingest_source,
        ingest_source=ingest_source,
        storage_path=storage_path,
        metadata_json=metadata_json,
        status=status,
    )
    session.add(doc)
    return doc


async def list_documents(
    session: AsyncSession, tenant_id: str, corpus_id: str | None = None
) -> list[Document]:
    # Tenant scoping prevents cross-tenant leakage.
    stmt = select(Document).where(Document.tenant_id == tenant_id)
    if corpus_id:
        stmt = stmt.where(Document.corpus_id == corpus_id)
    result = await session.execute(stmt.order_by(Document.created_at, Document.id))
    return list(result.scalars().all())


async def get_document(session: AsyncSession, tenant_id: str, document_id: str) -> Document | None:
    # Return None for tenant mismatch to keep 404 semantics.
    result = await session.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def get_document_by_id(session: AsyncSession, document_id: str) -> Document | None:
    # Use with care; tenant checks should be enforced by callers.
    result = await session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def count_chunks(session: AsyncSession, document_id: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    return int(result.scalar() or 0)


async def update_status(
    session: AsyncSession,
    document_id: str,
    *,
    status: str,
    error_message: str | None = None,
    last_reindexed_at: datetime | None = None,
) -> None:
    # Update status in-place so background tasks can progress state.
    result = await session.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        return
    doc.status = status
    doc.error_message = error_message
    if last_reindexed_at is not None:
        doc.last_reindexed_at = last_reindexed_at
