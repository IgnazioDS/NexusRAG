from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal

from arq import Retry, create_pool
from arq.connections import RedisSettings
from pydantic import BaseModel, Field

from nexusrag.core.config import get_settings
from nexusrag.persistence.db import SessionLocal
from nexusrag.persistence.repos import documents as documents_repo
from nexusrag.services.ingest.ingestion import (
    ingest_document_from_storage,
    write_text_to_storage,
)


logger = logging.getLogger(__name__)

_redis_pool = None
_redis_lock = asyncio.Lock()


class IngestionJobPayload(BaseModel):
    # Match the published job schema for API-to-worker handoff.
    tenant_id: str
    corpus_id: str
    document_id: str
    ingest_source: Literal["upload_file", "raw_text"]
    storage_path: str | None = None
    raw_text: str | None = None
    filename: str | None = None
    metadata_json: dict | None = None
    chunk_size_chars: int
    chunk_overlap_chars: int
    request_id: str
    # Internal flag to reuse ingestion code for reindex jobs.
    is_reindex: bool = False


def _utc_now() -> datetime:
    # Use UTC timestamps for consistency across API and worker processes.
    return datetime.now(timezone.utc)


async def get_redis_pool():
    # Cache the Redis pool to avoid reconnecting on every enqueue.
    global _redis_pool
    if _redis_pool is not None:
        return _redis_pool
    async with _redis_lock:
        if _redis_pool is None:
            settings = get_settings()
            _redis_pool = await create_pool(
                RedisSettings.from_dsn(settings.redis_url),
                default_queue_name=settings.ingest_queue_name,
            )
    return _redis_pool


async def enqueue_ingestion_job(payload: IngestionJobPayload) -> str:
    # Generate a stable job id so API callers can trace ingestion progress.
    job_id = payload.request_id
    settings = get_settings()
    if settings.ingest_execution_mode.lower() == "inline":
        await _run_inline_job(payload, job_id=job_id, max_retries=settings.ingest_max_retries)
        return job_id

    redis = await get_redis_pool()
    job = await redis.enqueue_job(
        "ingest_document",
        payload.model_dump(),
        _job_id=job_id,
        _queue_name=settings.ingest_queue_name,
    )
    # When a job id already exists, arq returns None; keep tracing with the same id.
    return job.job_id if job else job_id


async def process_ingestion_job(
    payload: IngestionJobPayload,
    *,
    job_id: str,
    attempt: int,
    max_retries: int,
) -> int:
    # Centralize ingestion execution so worker and inline mode share behavior.
    try:
        storage_path = _resolve_storage_path(payload)
        return await ingest_document_from_storage(
            payload.document_id,
            storage_path,
            chunk_size=payload.chunk_size_chars,
            chunk_overlap=payload.chunk_overlap_chars,
            is_reindex=payload.is_reindex,
            job_id=job_id,
        )
    except Exception as exc:  # noqa: BLE001 - surface a concise failure reason
        if _is_retryable(exc) and attempt < max_retries:
            # Let arq (or inline loop) retry transient failures.
            raise Retry() from exc
        await _mark_document_failed(
            payload.document_id,
            failure_reason=_failure_reason(exc),
            job_id=job_id,
        )
        logger.exception("Ingestion failed for %s", payload.document_id)
        return 0


async def _run_inline_job(payload: IngestionJobPayload, *, job_id: str, max_retries: int) -> None:
    # Inline mode mimics worker retries without requiring Redis.
    attempt = 1
    while True:
        try:
            await process_ingestion_job(
                payload,
                job_id=job_id,
                attempt=attempt,
                max_retries=max_retries,
            )
            return
        except Retry:
            attempt += 1
            continue


def _resolve_storage_path(payload: IngestionJobPayload) -> str:
    # Ensure a stable storage path is available for reindexing.
    if payload.storage_path:
        return payload.storage_path
    if payload.raw_text is not None:
        return write_text_to_storage(payload.document_id, payload.raw_text)
    raise ValueError("Ingestion payload missing storage_path or raw_text")


def _is_retryable(exc: Exception) -> bool:
    # Avoid retrying deterministic validation or missing-file failures.
    return not isinstance(exc, (FileNotFoundError, ValueError))


def _failure_reason(exc: Exception) -> str:
    # Return short, actionable messages without leaking stack traces.
    if isinstance(exc, FileNotFoundError):
        return "Stored document text is missing"
    if isinstance(exc, ValueError):
        return str(exc)
    return "Ingestion failed; retry or check worker logs"


async def _mark_document_failed(document_id: str, *, failure_reason: str, job_id: str) -> None:
    # Persist final failure state for operators and polling clients.
    async with SessionLocal() as session:
        await documents_repo.update_status(
            session,
            document_id,
            status="failed",
            error_message=failure_reason,
            failure_reason=failure_reason,
            completed_at=_utc_now(),
            last_job_id=job_id,
        )
        await session.commit()
