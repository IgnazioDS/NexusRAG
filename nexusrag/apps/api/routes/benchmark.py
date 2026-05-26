"""Public, unauthenticated /api/benchmark-latest endpoint.

Serves the most recent public retrieval benchmark run from a committed JSON
artifact (`nexusrag/benchmark/data/latest_run.json`) produced by the benchmark
runner and version-controlled in the repo. Same public contract as /api/stats:
HTTP 200 in every branch (never 5xx), CORS wildcard, cached.

Honesty: the artifact is computed by `python -m nexusrag.benchmark.runner` from
the committed `examples/benchmark-v1` fixture against the live retrieval path,
and every run is a git commit (fully inspectable, no prod DB write from CI).
`embedding_provider` records whether retrieval was semantic ("openai"/"vertex")
or lexical ("fake"). Returns status "pending" (not an error) until the first run
is committed, and "degraded" only if a present artifact is unreadable.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response

_log = logging.getLogger(__name__)
router = APIRouter()

SCHEMA_VERSION = 1
SYSTEM_SLUG = "nexusrag"

# Committed run artifact. From nexusrag/apps/api/routes/benchmark.py, parents[3]
# is the nexusrag package root; the runner writes the same path. Kept as an
# independent literal (not imported from the runner) so this public endpoint
# does not pull the runner's heavy retrieval/db imports into the request path.
_ARTIFACT = Path(__file__).resolve().parents[3] / "benchmark" / "data" / "latest_run.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _set_public_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"


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
async def benchmark_latest(response: Response) -> dict[str, Any]:
    _set_public_headers(response)
    if not _ARTIFACT.exists():
        # No run has been committed yet. Honest "pending", not an error.
        return _envelope("pending", None, None)
    try:
        data = json.loads(_ARTIFACT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:  # public contract forbids 5xx
        _log.warning("benchmark artifact unreadable", exc_info=exc)
        return _envelope("degraded", None, None)

    # Serve the committed run payloads as-is; only refresh the served-at stamp.
    return _envelope(
        str(data.get("status", "ok")),
        data.get("latest"),
        data.get("previous_run"),
    )
