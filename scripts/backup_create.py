from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from nexusrag.core.config import get_settings
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.backup import create_backup_job, run_backup_job


async def _run_backup(backup_type: str, output: str | None) -> None:
    # Execute a backup job from the CLI for operator workflows.
    settings = get_settings()
    output_dir = Path(output or settings.backup_local_dir)
    async with SessionLocal() as session:
        job = await create_backup_job(
            session,
            backup_type=backup_type,
            created_by_actor_id=None,
            tenant_scope=None,
            metadata={"source": "cli"},
        )
        await run_backup_job(
            session=session,
            job=job,
            backup_type=backup_type,
            output_dir=output_dir,
            actor_type="system",
            tenant_id=None,
            actor_id=None,
            actor_role=None,
            request_id=None,
        )
        print(f"backup_job_id={job.id}")
        print(f"manifest_uri={job.manifest_uri}")


def main() -> None:
    # Parse CLI flags for DR backup creation.
    parser = argparse.ArgumentParser(description="Create DR backups")
    parser.add_argument("--type", default="all", choices=["full", "schema", "metadata", "all"])
    parser.add_argument("--output", default=None)
    # Placeholder for future object storage uploads.
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()
    _ = args.no_upload
    asyncio.run(_run_backup(args.type, args.output))


if __name__ == "__main__":
    main()
