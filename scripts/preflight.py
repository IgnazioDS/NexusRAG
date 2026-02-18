from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from nexusrag.core.config import get_settings
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.ingest.queue import get_worker_heartbeat


def _latest_revision() -> str | None:
    # Resolve repository head revision directly from migration files for deterministic checks.
    versions = sorted(Path("nexusrag/persistence/alembic/versions").glob("*.py"))
    if not versions:
        return None
    latest = versions[-1]
    for line in latest.read_text(encoding="utf-8").splitlines():
        if line.startswith("revision ="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


async def _db_revision() -> str | None:
    # Query alembic_version to ensure the runtime schema matches repository head.
    async with SessionLocal() as session:
        return (await session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))).scalar_one_or_none()


async def _check_redis() -> bool:
    # Validate Redis reachability only when queue/rate-limit paths are enabled.
    settings = get_settings()
    if not (settings.rate_limit_enabled or settings.ingest_execution_mode == "queue"):
        return True
    client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        pong = await client.ping()
        return bool(pong)
    except Exception:
        return False
    finally:
        await client.aclose()


async def _check_compliance_status() -> tuple[bool, str | None]:
    # Fail preflight when the latest compliance snapshot is in fail state.
    async with SessionLocal() as session:
        status = (
            await session.execute(
                text(
                    "SELECT status FROM compliance_snapshots "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            )
        ).scalar_one_or_none()
    if status is None:
        return True, None
    return status != "fail", str(status)


def _required_env_names() -> list[str]:
    # Keep env requirements explicit and avoid printing secret values.
    return ["DATABASE_URL", "REDIS_URL", "AUTH_ENABLED"]


def _check_ops_routes() -> bool:
    # Confirm required ops endpoints are mounted before rollout.
    from nexusrag.apps.api.routes.ops import router as ops_router

    route_paths = {route.path for route in ops_router.routes}
    required = {"/ops/metrics", "/ops/slo", "/ops/health"}
    return required.issubset(route_paths)


async def run_preflight(*, output_json: str | None) -> int:
    settings = get_settings()
    results: list[dict[str, Any]] = []

    db_rev = await _db_revision()
    head_rev = _latest_revision()
    results.append(
        {
            "check": "alembic_current_matches_head",
            "status": "pass" if db_rev == head_rev else "fail",
            "detail": {"db_revision": db_rev, "head_revision": head_rev},
        }
    )

    missing_env = [name for name in _required_env_names() if not os.environ.get(name)]
    results.append(
        {
            "check": "required_env_present",
            "status": "pass" if not missing_env else "fail",
            "detail": {"missing": missing_env},
        }
    )

    redis_ok = await _check_redis()
    results.append({"check": "redis_reachable", "status": "pass" if redis_ok else "fail", "detail": {}})

    heartbeat = await get_worker_heartbeat()
    heartbeat_ok = heartbeat is not None
    if settings.preflight_require_worker_heartbeat:
        status = "pass" if heartbeat_ok else "fail"
    else:
        status = "pass" if heartbeat_ok else "warn"
    results.append(
        {
            "check": "worker_heartbeat_present",
            "status": status,
            "detail": {"heartbeat": heartbeat.isoformat() if heartbeat else None},
        }
    )

    results.append(
        {"check": "ops_routes_present", "status": "pass" if _check_ops_routes() else "fail", "detail": {}}
    )

    compliance_ok, compliance_status = await _check_compliance_status()
    results.append(
        {
            "check": "compliance_snapshot_not_failed",
            "status": "pass" if compliance_ok else "fail",
            "detail": {"latest_status": compliance_status},
        }
    )

    failed = [row for row in results if row["status"] == "fail"]
    summary = {
        "status": "pass" if not failed else "fail",
        "checks": results,
    }
    if output_json:
        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic deploy preflight checks.")
    parser.add_argument("--output-json", default="var/ops/preflight.json")
    args = parser.parse_args()
    return asyncio.run(run_preflight(output_json=args.output_json))


if __name__ == "__main__":
    sys.exit(main())
