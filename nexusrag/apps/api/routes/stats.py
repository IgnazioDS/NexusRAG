"""Public, unauthenticated /api/stats endpoint + /api/heartbeat liveness check.

Implements the Tier-A telemetry contract from
https://github.com/IgnazioDS/IgnazioDS/blob/main/TELEMETRY_SCHEMA.md.

The endpoint is consumed by the Production Telemetry panel on
https://eleventh.dev. Polling cadence is ~30s. Contract guarantees:

- HTTP 200 in all branches, even when the database is unreachable
- Privacy: aggregate counts only, no row-level fields ever leave this route
- CORS: wildcard origin (response is non-PII aggregates)
- Cache: public, max-age=30, stale-while-revalidate=60

The heartbeat endpoint is a shared-secret-protected POST liveness check. It
records NO workload data: /api/stats metrics reflect real /v1/run traffic only.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import get_db
from nexusrag.persistence.repos.query_log import (
    aggregate,
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
        # Real user-traffic workload (vs the prototypes' "benchmark"); lets the
        # homepage render "live · production" distinctly. Per the TELEMETRY_SCHEMA
        # workload field (IgnazioDS#2). Optional/additive, no schema_version bump.
        "workload": "production",
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
# A scheduled GitHub Actions workflow POSTs to this endpoint as an authenticated
# liveness check. It records NO query_log row and writes NO metrics: the public
# /api/stats workload figures must reflect real /v1/run traffic only. An earlier
# version synthesized latency + retrieval rows here to keep the widget "looking
# alive"; that fabrication was removed because the telemetry contract forbids
# seeded plausible values.
#
# Auth: shared secret in the Authorization header. If `HEARTBEAT_SECRET` is
# unset on the server, the endpoint disables itself (503).
#
# Not included in the OpenAPI schema; it's an operational hook.


async def _check_heartbeat_auth(request: Request) -> bool:
    expected = os.environ.get("HEARTBEAT_SECRET", "")
    if not expected:
        return False
    header = request.headers.get("Authorization", "")
    # Accept "Bearer <secret>" or the bare secret. Constant-time compare.
    provided = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else header.strip()
    return bool(provided) and secrets.compare_digest(expected, provided)


@router.post("/api/heartbeat", include_in_schema=False)
async def heartbeat(request: Request, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"

    if not os.environ.get("HEARTBEAT_SECRET"):
        # Endpoint is disabled on this deployment. 503 (Service Unavailable)
        # signals "feature not configured" without leaking which env var.
        response.status_code = 503
        return {"error": "heartbeat_disabled"}

    if not await _check_heartbeat_auth(request):
        response.status_code = 403
        return {"error": "unauthorized"}

    # Liveness acknowledgement ONLY. Deliberately records no query_log row and
    # writes no metrics: /api/stats counts, latency percentiles, and retrieval
    # size must reflect real /v1/run traffic exclusively. The 200 itself is the
    # liveness signal; last_active_at stays driven by real work.
    return {"status": "ok", "checked_at": _now_iso()}
