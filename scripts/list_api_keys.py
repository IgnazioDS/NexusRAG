from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import sys

from sqlalchemy import select

from nexusrag.domain.models import ApiKey, User
from nexusrag.persistence.db import SessionLocal


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_parser() -> argparse.ArgumentParser:
    # Keep listing scoped to one tenant to avoid accidental cross-tenant operator exposure.
    parser = argparse.ArgumentParser(description="List API keys for a tenant")
    parser.add_argument("--tenant", required=True, help="Tenant identifier")
    parser.add_argument(
        "--inactive-days",
        type=int,
        default=90,
        help="Highlight keys inactive for at least this number of days",
    )
    parser.add_argument(
        "--inactive-only",
        action="store_true",
        help="Show only inactive or expired keys",
    )
    return parser


async def _list_keys(args: argparse.Namespace) -> int:
    # Return deterministic key lifecycle metadata without exposing plaintext secrets.
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(ApiKey, User)
                .join(User, ApiKey.user_id == User.id)
                .where(ApiKey.tenant_id == args.tenant)
                .order_by(ApiKey.created_at.desc())
            )
        ).all()

    now = _utc_now()
    threshold = timedelta(days=max(1, int(args.inactive_days)))
    print(
        "key_id\tname\trole\tcreated_at\tlast_used_at\texpires_at\trevoked_at\tis_active\tinactive_days\tis_expired"
    )
    for api_key, user in rows:
        is_expired = api_key.expires_at is not None and api_key.expires_at <= now
        is_active = bool(user.is_active) and api_key.revoked_at is None and not is_expired
        anchor = api_key.last_used_at or api_key.created_at
        inactive_days = max(0, int((now - anchor).days))
        if args.inactive_only and timedelta(days=inactive_days) < threshold and not is_expired:
            continue
        print(
            f"{api_key.id}\t{api_key.name or ''}\t{user.role}\t"
            f"{api_key.created_at.isoformat()}\t"
            f"{api_key.last_used_at.isoformat() if api_key.last_used_at else ''}\t"
            f"{api_key.expires_at.isoformat() if api_key.expires_at else ''}\t"
            f"{api_key.revoked_at.isoformat() if api_key.revoked_at else ''}\t"
            f"{is_active}\t{inactive_days}\t{is_expired}"
        )
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_list_keys(args))
    except Exception as exc:  # noqa: BLE001 - show full operator-facing error context.
        print(f"list_api_keys failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
