from __future__ import annotations

import argparse
import asyncio
import sys

from nexusrag.persistence.db import SessionLocal
from nexusrag.services.compliance import create_compliance_snapshot


def _build_parser() -> argparse.ArgumentParser:
    # Keep CLI parameters explicit for repeatable evidence snapshots.
    parser = argparse.ArgumentParser(description="Create a compliance snapshot")
    parser.add_argument("--tenant", required=True, help="Tenant id")
    parser.add_argument("--actor", default=None, help="Actor id")
    return parser


async def _run(tenant_id: str, actor_id: str | None) -> int:
    async with SessionLocal() as session:
        row = await create_compliance_snapshot(session, tenant_id=tenant_id, created_by=actor_id)
    print(f"Created compliance snapshot {row.id} status={row.status}")
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    try:
        return asyncio.run(_run(args.tenant, args.actor))
    except Exception as exc:  # noqa: BLE001 - surface failure for CI diagnostics.
        print(f"compliance_snapshot failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
