"""Public, unauthenticated /api/benchmark-latest endpoint.

Publishes the most recent retrieval+generation benchmark run plus the
previous run (for a delta), from the benchmark_runs table. Same public
contract as /api/stats: HTTP 200 in every branch (never 5xx), CORS
wildcard, cached.

Honesty: results are real, computed from a fixed labeled fixture against
live retrieval/generation — nothing seeded. `embedding_provider` on each
run tells readers whether retrieval was semantic ("vertex") or lexical
("fake"). Returns status "pending" (not an error) until the first run.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import get_db
from nexusrag.domain.models import BenchmarkRun
from nexusrag.persistence.repos.benchmark import latest_runs

_log = logging.getLogger(__name__)
router = APIRouter()

SCHEMA_VERSION = 1
SYSTEM_SLUG = "nexusrag"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_public_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"


def _serialize(run: BenchmarkRun) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "fixture_version": run.fixture_version,
        "embedding_provider": run.embedding_provider,
        "generated_at": (
            run.generated_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if run.generated_at is not None
            else None
        ),
        "case_count": run.case_count,
        "metrics": run.metrics or {},
    }


def _envelope(status: str, latest: dict[str, Any] | None, previous: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "system": SYSTEM_SLUG,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "latest": latest,
        "previous_run": previous,
        "generated_at": _now_iso(),
    }


@router.options("/api/benchmark-latest", include_in_schema=False)
async def benchmark_latest_options(response: Response) -> Response:
    _set_public_headers(response)
    response.status_code = 204
    return response


@router.get("/api/benchmark-latest")
async def benchmark_latest(
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _set_public_headers(response)
    try:
        runs = await latest_runs(session, limit=2)
    except Exception as exc:  # noqa: BLE001 - public contract forbids 5xx
        _log.warning("benchmark-latest read failed", exc_info=exc)
        return _envelope("degraded", None, None)

    if not runs:
        return _envelope("pending", None, None)

    latest = _serialize(runs[0])
    previous = _serialize(runs[1]) if len(runs) > 1 else None
    return _envelope("ok", latest, previous)
