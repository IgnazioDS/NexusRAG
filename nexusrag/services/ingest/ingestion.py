from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import EMBED_DIM
from nexusrag.domain.models import Chunk, Document
from nexusrag.ingestion.chunking import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    chunk_text,
)
from nexusrag.ingestion.embeddings import embed_text
from nexusrag.persistence.db import SessionLocal
from nexusrag.persistence.repos import documents as documents_repo


DOCUMENT_STORAGE_DIR = Path("var/documents")


def _ensure_storage_dir() -> Path:
    # Local storage is a dev-friendly placeholder until object storage is added.
    DOCUMENT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return DOCUMENT_STORAGE_DIR


def build_storage_path(document_id: str) -> str:
    # Use deterministic filenames to make reindexing stable and idempotent.
    return str(_ensure_storage_dir() / f"{document_id}.txt")


def write_text_to_storage(document_id: str, text: str) -> str:
    # Persisting the raw text enables reindexing without reuploading.
    storage_path = build_storage_path(document_id)
    Path(storage_path).write_text(text, encoding="utf-8")
    return storage_path


def read_text_from_storage(storage_path: str) -> str:
    # Fail fast if the storage path is missing so callers can report 409.
    return Path(storage_path).read_text(encoding="utf-8")


async def _load_document(session: AsyncSession, document_id: str) -> Document | None:
    result = await session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def _ingest_with_session(
    session: AsyncSession,
    doc: Document,
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    is_reindex: bool,
) -> int:
    # Mark processing early so operators can see progress on long ingestions.
    doc.status = "processing"
    doc.error_message = None
    await session.commit()

    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))

    chunks: list[Chunk] = []
    for index, (chunk_text_value, start, end) in enumerate(
        chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    ):
        embedding = embed_text(chunk_text_value)
        if len(embedding) != EMBED_DIM:
            raise ValueError(f"Embedding dimension mismatch; expected {EMBED_DIM}.")
        metadata = {
            "filename": doc.filename,
            "content_type": doc.content_type,
            "offset_start": start,
            "offset_end": end,
        }
        if doc.metadata_json:
            # Keep document-level metadata attached to every chunk for retrieval.
            metadata["document_metadata"] = doc.metadata_json
        chunks.append(
            Chunk(
                id=uuid4(),
                corpus_id=doc.corpus_id,
                document_id=doc.id,
                document_uri=f"document://{doc.id}",
                chunk_index=index,
                text=chunk_text_value,
                embedding=embedding,
                metadata_json=metadata,
            )
        )

    session.add_all(chunks)
    doc.status = "succeeded"
    doc.error_message = None
    if is_reindex:
        # Use UTC timestamps to keep status fields deterministic across hosts.
        doc.last_reindexed_at = datetime.now(timezone.utc)
    await session.commit()
    return len(chunks)


async def ingest_document(
    document_id: str,
    text: str,
    *,
    chunk_size: int = CHUNK_SIZE_CHARS,
    chunk_overlap: int = CHUNK_OVERLAP_CHARS,
    is_reindex: bool = False,
) -> int:
    # Run ingestion in a background task with its own DB session.
    async with SessionLocal() as session:
        doc = await _load_document(session, document_id)
        if doc is None:
            return 0

        try:
            return await _ingest_with_session(
                session,
                doc,
                text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                is_reindex=is_reindex,
            )
        except Exception as exc:  # noqa: BLE001 - store an error message for operators
            await session.rollback()
            await documents_repo.update_status(
                session,
                document_id,
                status="failed",
                error_message=str(exc),
            )
            await session.commit()
            raise


async def ingest_document_from_storage(
    document_id: str,
    storage_path: str,
    *,
    chunk_size: int = CHUNK_SIZE_CHARS,
    chunk_overlap: int = CHUNK_OVERLAP_CHARS,
    is_reindex: bool = False,
) -> int:
    # Read the stored source text to keep ingestion repeatable.
    text = read_text_from_storage(storage_path)
    return await ingest_document(
        document_id,
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        is_reindex=is_reindex,
    )
