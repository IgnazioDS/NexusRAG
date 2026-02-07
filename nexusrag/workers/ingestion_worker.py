from __future__ import annotations

import asyncio
import logging

from arq.connections import RedisSettings

from nexusrag.core.config import get_settings
from nexusrag.services.ingest.queue import (
    IngestionJobPayload,
    process_ingestion_job,
    set_worker_heartbeat,
)


logger = logging.getLogger(__name__)


async def ingest_document(ctx, payload: dict) -> int:
    # Parse and validate payloads in the worker to enforce schema contracts.
    job_payload = IngestionJobPayload.model_validate(payload)
    settings = get_settings()
    job_id = ctx.get("job_id") or job_payload.request_id
    attempt = ctx.get("job_try", 1)
    return await process_ingestion_job(
        job_payload,
        job_id=job_id,
        attempt=attempt,
        max_retries=settings.ingest_max_retries,
    )


async def _heartbeat_loop() -> None:
    # Emit heartbeats on a fixed interval for ops health reporting.
    settings = get_settings()
    while True:
        await set_worker_heartbeat()
        await asyncio.sleep(settings.worker_heartbeat_interval_s)


async def _startup(ctx) -> None:
    # Start the heartbeat task when the worker boots.
    ctx["heartbeat_task"] = asyncio.create_task(_heartbeat_loop())


async def _shutdown(ctx) -> None:
    # Cancel the heartbeat task to avoid dangling coroutines on exit.
    task = ctx.get("heartbeat_task")
    if task:
        task.cancel()


class WorkerSettings:
    # Keep worker configuration as class attributes for arq CLI compatibility.
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.ingest_queue_name
    max_tries = settings.ingest_max_retries
    functions = [ingest_document]
    on_startup = _startup
    on_shutdown = _shutdown
