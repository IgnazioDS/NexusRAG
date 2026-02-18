from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from nexusrag.core.config import get_settings
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.operability.alerts import evaluate_alert_rules, list_alerting_tenant_ids
from nexusrag.services.operability.notifications import (
    claim_due_notification_jobs,
    process_notification_job,
)
from nexusrag.services.resilience import get_resilience_redis


logger = logging.getLogger(__name__)

OPERABILITY_EVAL_LOCK_KEY = "nexusrag:ops:evaluator:lock"
OPERABILITY_WORKER_HEARTBEAT_KEY = "operability_worker_heartbeat_ts"

_local_lock = asyncio.Lock()
_local_lock_owner: str | None = None


def _utc_now() -> datetime:
    # Keep worker timestamps in UTC to avoid skew between API and background processes.
    return datetime.now(timezone.utc)


def _is_missing_table_error(exc: Exception) -> bool:
    # Allow worker loops to start before migrations by treating missing-table errors as temporary degraded state.
    message = str(exc).lower()
    return "undefinedtableerror" in message or "does not exist" in message


@dataclass(slots=True)
class EvaluatorLock:
    token: str
    redis: Any | None
    local: bool


async def acquire_evaluator_lock() -> EvaluatorLock | None:
    # Coordinate evaluator ownership so only one worker evaluates and opens incidents per interval.
    settings = get_settings()
    token = uuid4().hex
    redis = await get_resilience_redis()
    ttl_s = max(5, int(settings.operability_eval_lock_ttl_s))
    if redis is not None:
        acquired = await redis.set(OPERABILITY_EVAL_LOCK_KEY, token, nx=True, ex=ttl_s)
        if not acquired:
            return None
        return EvaluatorLock(token=token, redis=redis, local=False)

    # Fall back to an in-process lock for deterministic local and test environments.
    global _local_lock_owner
    if _local_lock.locked():
        return None
    await _local_lock.acquire()
    _local_lock_owner = token
    return EvaluatorLock(token=token, redis=None, local=True)


async def release_evaluator_lock(lock: EvaluatorLock) -> None:
    # Release only if this worker still owns the token to avoid clobbering a newer lock holder.
    global _local_lock_owner
    if lock.local:
        if _local_lock.locked() and _local_lock_owner == lock.token:
            _local_lock_owner = None
            _local_lock.release()
        return
    if lock.redis is None:
        return
    current = await lock.redis.get(OPERABILITY_EVAL_LOCK_KEY)
    value = current.decode("utf-8") if isinstance(current, (bytes, bytearray)) else str(current or "")
    if value == lock.token:
        await lock.redis.delete(OPERABILITY_EVAL_LOCK_KEY)


async def set_operability_worker_heartbeat(*, timestamp: datetime | None = None) -> None:
    # Publish heartbeat timestamps so ops surfaces can detect evaluator stalls independently of request traffic.
    redis = await get_resilience_redis()
    if redis is None:
        return
    heartbeat = timestamp or _utc_now()
    stale_after = max(60, int(get_settings().operability_worker_heartbeat_stale_after_s))
    await redis.set(OPERABILITY_WORKER_HEARTBEAT_KEY, heartbeat.isoformat(), ex=stale_after * 10)


async def get_operability_worker_heartbeat() -> datetime | None:
    # Return None when heartbeat is missing/unreadable so ops endpoints can degrade gracefully.
    redis = await get_resilience_redis()
    if redis is None:
        return None
    value = await redis.get(OPERABILITY_WORKER_HEARTBEAT_KEY)
    if not value:
        return None
    decoded = value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)
    try:
        return datetime.fromisoformat(decoded)
    except ValueError:
        return None


async def run_background_evaluator_cycle() -> dict[str, Any]:
    # Evaluate alerts headlessly across tenants so incident automation no longer depends on live API traffic.
    settings = get_settings()
    if not settings.operability_background_evaluator_enabled:
        return {"status": "disabled", "tenants_evaluated": 0, "alerts_triggered": 0}
    lock = await acquire_evaluator_lock()
    if lock is None:
        return {"status": "skipped_lock", "tenants_evaluated": 0, "alerts_triggered": 0}

    evaluated = 0
    triggered = 0
    try:
        try:
            async with SessionLocal() as session:
                tenant_ids = await list_alerting_tenant_ids(session=session)
                for tenant_id in tenant_ids:
                    rows = await evaluate_alert_rules(
                        session=session,
                        tenant_id=tenant_id,
                        window="5m",
                        actor_id="operability_worker",
                        actor_role="system",
                        request_id=None,
                    )
                    evaluated += 1
                    triggered += len(rows)
        except SQLAlchemyError as exc:
            if _is_missing_table_error(exc):
                return {"status": "waiting_for_migrations", "tenants_evaluated": 0, "alerts_triggered": 0}
            raise
        await set_operability_worker_heartbeat()
        return {"status": "ok", "tenants_evaluated": evaluated, "alerts_triggered": triggered}
    finally:
        await release_evaluator_lock(lock)


async def run_notification_delivery_cycle(*, limit: int = 50) -> dict[str, int]:
    # Drain due notification jobs in bounded batches for deterministic retry throughput.
    try:
        async with SessionLocal() as session:
            job_ids = await claim_due_notification_jobs(session=session, limit=limit)
    except SQLAlchemyError as exc:
        if _is_missing_table_error(exc):
            return {"claimed": 0, "processed": 0}
        raise
    processed = 0
    for job_id in job_ids:
        async with SessionLocal() as session:
            row = await process_notification_job(session=session, job_id=job_id)
            if row is not None:
                processed += 1
    return {"claimed": len(job_ids), "processed": processed}


async def run_background_evaluator_loop() -> None:
    # Run evaluator on a fixed cadence and continue after failures to preserve operability liveness.
    interval = max(5, int(get_settings().operability_eval_interval_s))
    while True:
        try:
            await run_background_evaluator_cycle()
        except Exception:  # noqa: BLE001 - keep loop alive while surfacing errors in logs.
            logger.exception("operability evaluator cycle failed")
        await asyncio.sleep(interval)


async def run_notification_delivery_loop() -> None:
    # Run notification delivery polling continuously to convert queued jobs into attempts/outcomes.
    interval = max(1, int(get_settings().notify_worker_poll_interval_s))
    while True:
        try:
            await run_notification_delivery_cycle()
        except Exception:  # noqa: BLE001 - keep loop alive while surfacing errors in logs.
            logger.exception("notification delivery cycle failed")
        await asyncio.sleep(interval)
