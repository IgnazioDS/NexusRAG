from __future__ import annotations

import logging

from arq.connections import RedisSettings

from nexusrag.core.config import get_settings
from nexusrag.services.ingest.queue import IngestionJobPayload, process_ingestion_job


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


class WorkerSettings:
    # Keep worker configuration as class attributes for arq CLI compatibility.
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.ingest_queue_name
    max_tries = settings.ingest_max_retries
    functions = [ingest_document]
