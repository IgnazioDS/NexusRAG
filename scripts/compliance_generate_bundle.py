from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from nexusrag.core.config import get_settings
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.compliance import generate_evidence_bundle


def _parse_datetime(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _run_bundle(bundle_type: str, period_start: str | None, period_end: str | None) -> None:
    # Generate a SOC 2 evidence bundle from the CLI for auditors.
    settings = get_settings()
    now = datetime.now(timezone.utc)
    start = _parse_datetime(period_start, now - timedelta(days=settings.compliance_default_window_days))
    end = _parse_datetime(period_end, now)
    async with SessionLocal() as session:
        result = await generate_evidence_bundle(
            session,
            bundle_type=bundle_type,
            period_start=start,
            period_end=end,
            tenant_scope=None,
            generated_by_actor_id=None,
        )
        print(f"bundle_id={result.bundle_id}")
        print(f"manifest_uri={result.manifest_uri}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SOC 2 evidence bundle")
    parser.add_argument("--bundle-type", default="soc2_on_demand")
    parser.add_argument("--period-start", default=None)
    parser.add_argument("--period-end", default=None)
    args = parser.parse_args()
    asyncio.run(_run_bundle(args.bundle_type, args.period_start, args.period_end))


if __name__ == "__main__":
    main()
