from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from nexusrag.core.config import get_settings
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.backup import prune_backups


async def _run_prune(retention_days: int, base_dir: str | None, dry_run: bool) -> None:
    # Prune backup artifacts beyond retention for DR hygiene.
    settings = get_settings()
    backup_dir = Path(base_dir or settings.backup_local_dir)
    if dry_run:
        print("dry_run=true")
        return
    async with SessionLocal() as session:
        pruned = await prune_backups(
            session=session,
            base_dir=backup_dir,
            retention_days=retention_days,
        )
        print(f"pruned_backups={pruned}")


def main() -> None:
    # Parse CLI flags for backup retention pruning.
    parser = argparse.ArgumentParser(description="Prune DR backups beyond retention")
    parser.add_argument("--retention-days", type=int, default=None)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    retention = args.retention_days or settings.backup_retention_days
    asyncio.run(_run_prune(retention, args.base_dir, args.dry_run))


if __name__ == "__main__":
    main()
