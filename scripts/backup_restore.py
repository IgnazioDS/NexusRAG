from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nexusrag.core.config import get_settings
from nexusrag.services.backup import restore_from_manifest


def main() -> None:
    # Restore backup artifacts from a manifest with safety checks.
    parser = argparse.ArgumentParser(description="Restore DR backups")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--components", default="all")
    parser.add_argument("--target-db-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    target_db_url = args.target_db_url or settings.database_url
    components = [item.strip() for item in args.components.split(",") if item.strip()]

    report = restore_from_manifest(
        manifest_path=Path(args.manifest),
        components=components,
        target_db_url=target_db_url,
        dry_run=args.dry_run,
        allow_destructive=args.allow_destructive,
    )
    print(json.dumps(report.__dict__, indent=2))
    if report.status != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()
