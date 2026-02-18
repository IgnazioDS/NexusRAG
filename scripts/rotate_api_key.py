from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import sys

from sqlalchemy import select

from nexusrag.domain.models import ApiKey
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.auth.api_keys import generate_api_key
from nexusrag.services.audit import record_event


def _build_parser() -> argparse.ArgumentParser:
    # Keep rotation CLI explicit to reduce accidental key replacement risk.
    parser = argparse.ArgumentParser(description="Rotate an API key and revoke the previous credential")
    parser.add_argument("old_key_id", help="API key id to rotate")
    parser.add_argument("--name", default=None, help="Optional label for the new key")
    parser.add_argument(
        "--keep-old-active",
        action="store_true",
        help="Keep the previous key active (default is to revoke it after rotation)",
    )
    return parser


async def _rotate(args: argparse.Namespace) -> int:
    # Rotate by minting a new key for the same user/tenant and revoking the previous key atomically.
    async with SessionLocal() as session:
        old_key = (
            await session.execute(select(ApiKey).where(ApiKey.id == args.old_key_id))
        ).scalar_one_or_none()
        if old_key is None:
            raise ValueError("API key not found")
        if old_key.revoked_at is not None:
            raise ValueError("API key is already revoked")

        new_id, raw_key, key_prefix, key_hash = generate_api_key()
        new_key = ApiKey(
            id=new_id,
            user_id=old_key.user_id,
            tenant_id=old_key.tenant_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            name=args.name or old_key.name,
            expires_at=old_key.expires_at,
        )
        if not args.keep_old_active:
            # Default to revoking the previous key to enforce one-active-key rotation hygiene.
            old_key.revoked_at = datetime.now(timezone.utc)
        session.add(new_key)
        await session.commit()

        await record_event(
            session=session,
            tenant_id=old_key.tenant_id,
            actor_type="system",
            actor_id="rotate_api_key",
            actor_role=None,
            event_type="auth.api_key.rotated",
            outcome="success",
            resource_type="api_key",
            resource_id=new_key.id,
            metadata={
                "rotated_from": old_key.id,
                "new_key_id": new_key.id,
                "user_id": old_key.user_id,
                "name": new_key.name,
                "old_key_revoked": not args.keep_old_active,
            },
            commit=True,
            best_effort=False,
        )

    print("API key rotated:")
    print(f"  old_key_id: {args.old_key_id}")
    print(f"  new_key_id: {new_id}")
    print(f"  old_key_revoked: {not args.keep_old_active}")
    print(f"  key_prefix: {key_prefix}")
    print("  api_key:")
    print(f"    {raw_key}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_rotate(args))
    except Exception as exc:  # noqa: BLE001 - surface rotation failures clearly in CLI output.
        print(f"rotate_api_key failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
