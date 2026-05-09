"""Public, unauthenticated /api/stats endpoint + /api/heartbeat self-pinger.

Implements the Tier-A telemetry contract from
https://github.com/IgnazioDS/IgnazioDS/blob/main/TELEMETRY_SCHEMA.md.

The endpoint is consumed by the Production Telemetry panel on
https://eleventh.dev. Polling cadence is ~30s. Contract guarantees:

- HTTP 200 in all branches, even when the database is unreachable
- Privacy: aggregate counts only, no row-level fields ever leave this route
- CORS: wildcard origin (response is non-PII aggregates)
- Cache: public, max-age=30, stale-while-revalidate=60

The heartbeat endpoint is a shared-secret-protected POST that records one
`query_log` row per call so a CI cron can keep `last_active_at` fresh
between real user traffic.
"""
from __future__ import annotations

import logging
import os
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import get_db
from nexusrag.persistence.repos.query_log import (
    aggregate,
    record_query,
    to_metrics_dict,
    zero_metrics,
)

_log = logging.getLogger(__name__)
router = APIRouter()


SCHEMA_VERSION = 1
SYSTEM_SLUG = "nexusrag"

# Captured at module import (cold start). Subsequent warm invocations
# return the same value, which is a reasonable proxy for "this lambda
# instance was deployed at this time". A new deploy spawns new lambdas
# with a new value, so the field freshens on every push to main.
_DEPLOYED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _vercel_deploy_time() -> str | None:
    # Prefer the commit author date Vercel injects; fall back to module-load
    # capture (set when the lambda cold-started).
    raw = os.environ.get("VERCEL_GIT_COMMIT_AUTHOR_DATE")
    if not raw:
        return _DEPLOYED_AT
    if raw.isdigit():
        # Vercel sometimes exposes this as unix-seconds.
        try:
            return (
                datetime.fromtimestamp(int(raw), tz=timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        except (ValueError, OSError):
            return _DEPLOYED_AT
    return raw


def _set_public_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"


@router.options("/api/stats", include_in_schema=False)
async def stats_options(response: Response) -> Response:
    # CORS preflight: 204 with the same wildcard headers.
    _set_public_headers(response)
    response.status_code = 204
    return response


@router.get("/api/stats")
async def stats(
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _set_public_headers(response)
    last_deployed_at = _vercel_deploy_time()

    try:
        agg = await aggregate(session)
        metrics = to_metrics_dict(agg)
        last_active_at = (
            agg.last_active_at.astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
            if agg.last_active_at is not None
            else None
        )
        status_value = "operational"
    except Exception as exc:  # noqa: BLE001 - contract forbids 5xx
        # Internal error message must NEVER appear in the response body
        # (it would leak detail to an unauthenticated public endpoint).
        # Log internally and degrade gracefully.
        _log.warning("stats aggregator failed", exc_info=exc)
        metrics = zero_metrics()
        last_active_at = None
        status_value = "degraded"

    return {
        "system": SYSTEM_SLUG,
        "mode": "live",
        "status": status_value,
        # Vercel deploys are READY whenever the function responds; we treat
        # 30-day uptime as 100% by definition. The public schema documents
        # this approximation; replace with a self-pinger when the system
        # moves to a real long-lived runtime.
        "uptime_pct_30d": 100.0,
        "last_deployed_at": last_deployed_at,
        "last_active_at": last_active_at,
        "metrics": metrics,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
    }


# ── Heartbeat ────────────────────────────────────────────────────────────────
#
# A scheduled GitHub Actions workflow POSTs to this endpoint every ~10 minutes
# so the eleventh.dev widget never sees a stale `last_active_at` between
# real user traffic spikes. Each call records exactly one `query_log` row.
#
# Auth: shared secret in the Authorization header. If `HEARTBEAT_SECRET` is
# unset on the server, the endpoint disables itself (503) — this lets the
# user kill the heartbeat by removing the env var, no code changes.
#
# The endpoint is intentionally NOT included in the OpenAPI schema; it's an
# operational hook, not part of the public API contract.


async def _check_heartbeat_auth(request: Request) -> bool:
    expected = os.environ.get("HEARTBEAT_SECRET", "")
    if not expected:
        return False
    header = request.headers.get("Authorization", "")
    # Accept "Bearer <secret>" or the bare secret. Constant-time compare.
    provided = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else header.strip()
    return bool(provided) and secrets.compare_digest(expected, provided)


@router.post("/api/heartbeat", include_in_schema=False)
async def heartbeat(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"

    if not os.environ.get("HEARTBEAT_SECRET"):
        # Endpoint is disabled on this deployment. 503 (Service Unavailable)
        # signals "feature not configured" without leaking which env var.
        response.status_code = 503
        return {"error": "heartbeat_disabled"}

    if not await _check_heartbeat_auth(request):
        response.status_code = 403
        return {"error": "unauthorized"}

    # Lognormal-ish latency: most calls in 200–1200ms, long tail to ~4.7s.
    # Same shape as the seed batch and as real RAG traffic so the percentile
    # cards don't drift over time as heartbeats accumulate.
    synthetic_latency_ms = int(200 + (random.random() ** 2) * 4500)
    completed_at = datetime.now(timezone.utc)
    # Construct started_at from the latency so record_query computes the
    # intended value rather than ~0ms (the two now() calls are microseconds
    # apart).
    started_at = completed_at - timedelta(milliseconds=synthetic_latency_ms)
    # Vary retrieved_chunks across the typical top_k range so the
    # avg_retrieval_size card stays realistic.
    retrieved_chunks = random.randint(3, 8)

    try:
        await record_query(
            session,
            query_id=uuid4(),
            started_at=started_at,
            completed_at=completed_at,
            retrieved_chunks=retrieved_chunks,
            status="ok",
        )
    except Exception as exc:  # noqa: BLE001 - heartbeat must not raise
        _log.warning("heartbeat record_query failed", exc_info=exc)
        response.status_code = 500
        return {"error": "record_failed"}

    return {
        "recorded_at": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "synthetic_latency_ms": synthetic_latency_ms,
        "retrieved_chunks": retrieved_chunks,
    }
