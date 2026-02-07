from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import update

from nexusrag.domain.models import ApiKey
from nexusrag.persistence.db import SessionLocal


def _build_parser() -> argparse.ArgumentParser:
    # Keep CLI usage minimal to avoid revoking the wrong key.
    parser = argparse.ArgumentParser(description="Revoke an API key by id")
    parser.add_argument("key_id", help="API key id to revoke")
    return parser


async def _revoke_key(key_id: str) -> int:
    # Mark the key revoked without deleting history for audits.
    async with SessionLocal() as session:
        result = await session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(revoked_at=datetime.now(timezone.utc))
        )
        if result.rowcount == 0:
            raise ValueError("API key not found")
        await session.commit()
    print(f"Revoked API key {key_id}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_revoke_key(args.key_id))
    except Exception as exc:  # noqa: BLE001 - surface provisioning failures clearly
        print(f"revoke_api_key failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
