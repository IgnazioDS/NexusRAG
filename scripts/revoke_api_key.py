from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import select, update

from nexusrag.domain.models import ApiKey
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.audit import record_event


def _build_parser() -> argparse.ArgumentParser:
    # Keep CLI usage minimal to avoid revoking the wrong key.
    parser = argparse.ArgumentParser(description="Revoke an API key by id")
    parser.add_argument("key_id", help="API key id to revoke")
    return parser


async def _revoke_key(key_id: str) -> int:
    # Mark the key revoked without deleting history for audits.
    async with SessionLocal() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
        api_key = result.scalar_one_or_none()
        if api_key is None:
            raise ValueError("API key not found")

        result = await session.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await session.commit()

        # Record API key revocations for security investigations.
        await record_event(
            session=session,
            tenant_id=api_key.tenant_id,
            actor_type="system",
            actor_id="revoke_api_key",
            actor_role=None,
            event_type="auth.api_key.revoked",
            outcome="success",
            resource_type="api_key",
            resource_id=api_key.id,
            metadata={
                "user_id": api_key.user_id,
                "key_prefix": api_key.key_prefix,
                "key_name": api_key.name,
            },
            commit=True,
            best_effort=False,
        )
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
