from __future__ import annotations

import asyncio
import logging

from arq.connections import RedisSettings

from nexusrag.core.config import get_settings
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.operability.notifications import (
    enqueue_due_notification_jobs,
    process_notification_delivery,
)

logger = logging.getLogger(__name__)


async def deliver_notification_delivery(ctx, delivery_id: str) -> str:
    # Consume queued delivery ids and process one destination-scoped delivery attempt.
    async with SessionLocal() as session:
        row = await process_notification_delivery(session=session, delivery_id=delivery_id)
    return "processed" if row is not None else "skipped"


async def _scheduler_loop() -> None:
    # Re-enqueue due jobs on a bounded cadence to recover from transient enqueue/worker outages.
    settings = get_settings()
    interval_s = max(1, int(settings.notify_worker_poll_interval_s))
    batch = max(1, int(settings.notify_requeue_batch_size))
    while True:
        try:
            async with SessionLocal() as session:
                await enqueue_due_notification_jobs(session=session, limit=batch)
        except Exception:  # noqa: BLE001 - keep scheduler alive while surfacing failures in worker logs.
            logger.exception("notification due-job scheduler failed")
        await asyncio.sleep(interval_s)


async def _startup(ctx) -> None:
    # Start due-job scheduler with the worker so retries continue even when API traffic is idle.
    ctx["scheduler_task"] = asyncio.create_task(_scheduler_loop())


async def _shutdown(ctx) -> None:
    # Cancel scheduler task on shutdown to avoid dangling coroutines in tests and local runs.
    task = ctx.get("scheduler_task")
    if task:
        task.cancel()


class WorkerSettings:
    # Keep worker settings as class attributes for ARQ CLI compatibility.
    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.notify_queue_name
    max_tries = max(1, int(settings.notify_max_attempts))
    functions = [deliver_notification_delivery]
    on_startup = _startup
    on_shutdown = _shutdown
