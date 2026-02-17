from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import EMBED_DIM, get_settings
from nexusrag.domain.models import Chunk, Document
from nexusrag.ingestion.chunking import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_SIZE_CHARS,
    chunk_text,
)
from nexusrag.ingestion.embeddings import embed_text
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.costs.metering import estimate_tokens, record_cost_event
from nexusrag.services.telemetry import record_segment_timing, set_gauge


logger = logging.getLogger(__name__)


DOCUMENT_STORAGE_DIR = Path("var/documents")


def _utc_now() -> datetime:
    # Use UTC timestamps for deterministic status tracking across hosts.
    return datetime.now(timezone.utc)


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
    job_id: str | None,
) -> int:
    # Mark processing early so operators can see progress on long ingestions.
    started = _utc_now()
    queue_wait_ms: float | None = None
    if doc.queued_at is not None:
        queue_wait_ms = max(0.0, (started - doc.queued_at).total_seconds() * 1000.0)
        # Publish queue wait gauges for ingestion backlog visibility.
        set_gauge("ingest.queue_wait_ms.latest", queue_wait_ms)
        record_segment_timing(route_class="ingest", segment="queue_wait", latency_ms=queue_wait_ms)
    doc.status = "processing"
    doc.error_message = None
    doc.failure_reason = None
    doc.processing_started_at = started
    doc.completed_at = None
    if job_id:
        # Persist the job id so operators can trace worker activity.
        doc.last_job_id = job_id
    await session.commit()

    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))

    chunks: list[Chunk] = []
    # Validate chunk parameters to avoid infinite loops in windowing.
    _validate_chunk_params(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
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
    doc.failure_reason = None
    completed = _utc_now()
    doc.completed_at = completed
    processing_duration_ms = max(0.0, (completed - started).total_seconds() * 1000.0)
    # Publish processing duration gauges for worker saturation diagnostics.
    set_gauge("ingest.processing_duration_ms.latest", processing_duration_ms)
    record_segment_timing(route_class="ingest", segment="processing_duration", latency_ms=processing_duration_ms)
    if is_reindex:
        # Use UTC timestamps to keep status fields deterministic across hosts.
        doc.last_reindexed_at = _utc_now()
    await session.commit()
    # Record embedding costs after the ingest commit so ingestion state stays consistent.
    try:
        settings = get_settings()
        ratio = settings.cost_estimator_token_chars_ratio or 4.0
        token_count = estimate_tokens(text, ratio=ratio)
        await record_cost_event(
            session=None,
            tenant_id=doc.tenant_id,
            request_id=job_id,
            session_id=None,
            route_class="ingest",
            component="embedding",
            provider="internal",
            units={"tokens": token_count, "chunks": len(chunks)},
            rate_type="per_1k_tokens",
            metadata={"estimated": True, "reindex": is_reindex},
        )
    except Exception as exc:  # noqa: BLE001 - best-effort metering should not fail ingestion
        logger.warning("cost_metering_embedding_failed document_id=%s", doc.id, exc_info=exc)
    return len(chunks)


async def ingest_document(
    document_id: str,
    text: str,
    *,
    chunk_size: int = CHUNK_SIZE_CHARS,
    chunk_overlap: int = CHUNK_OVERLAP_CHARS,
    is_reindex: bool = False,
    job_id: str | None = None,
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
                job_id=job_id,
            )
        except Exception:  # noqa: BLE001 - upstream handles failure state and retries
            await session.rollback()
            raise


async def ingest_document_from_storage(
    document_id: str,
    storage_path: str,
    *,
    chunk_size: int = CHUNK_SIZE_CHARS,
    chunk_overlap: int = CHUNK_OVERLAP_CHARS,
    is_reindex: bool = False,
    job_id: str | None = None,
) -> int:
    # Read the stored source text to keep ingestion repeatable.
    text = read_text_from_storage(storage_path)
    return await ingest_document(
        document_id,
        text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        is_reindex=is_reindex,
        job_id=job_id,
    )


def _validate_chunk_params(*, chunk_size: int, chunk_overlap: int) -> None:
    # Guard against invalid ranges that would cause non-terminating chunking.
    if chunk_size < 1 or chunk_overlap < 0:
        raise ValueError("chunk_size_chars must be >= 1 and chunk_overlap_chars must be >= 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")
