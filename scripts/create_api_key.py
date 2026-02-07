from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import uuid4

from nexusrag.domain.models import ApiKey, User
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.auth.api_keys import generate_api_key, normalize_role
from nexusrag.services.audit import record_event


def _build_parser() -> argparse.ArgumentParser:
    # Keep CLI arguments explicit to avoid accidental key misuse.
    parser = argparse.ArgumentParser(description="Create an API key for a tenant")
    parser.add_argument("--tenant", required=True, help="Tenant identifier")
    parser.add_argument("--role", required=True, help="Role: reader|editor|admin")
    parser.add_argument("--name", required=True, help="Key label for auditing")
    parser.add_argument("--user-id", default=None, help="Existing user id to attach")
    parser.add_argument("--email", default=None, help="Optional user email")
    return parser


async def _create_key(args: argparse.Namespace) -> int:
    # Normalize role before writing it to the database.
    role = normalize_role(args.role)
    user_id = args.user_id or uuid4().hex
    key_id, raw_key, key_prefix, key_hash = generate_api_key()

    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                tenant_id=args.tenant,
                email=args.email,
                role=role,
                is_active=True,
            )
            session.add(user)
        else:
            # Ensure existing users stay tenant-bound when issuing new keys.
            if user.tenant_id != args.tenant:
                raise ValueError("User tenant_id does not match requested tenant")
            if user.role != role:
                user.role = role
            if args.email and user.email != args.email:
                user.email = args.email
        # Flush the user row before inserting API keys to satisfy FK constraints.
        await session.flush()

        api_key = ApiKey(
            id=key_id,
            user_id=user.id,
            tenant_id=user.tenant_id,
            key_prefix=key_prefix,
            key_hash=key_hash,
            name=args.name,
        )
        session.add(api_key)
        await session.commit()

        # Record API key creation for security investigations.
        await record_event(
            session=session,
            tenant_id=user.tenant_id,
            actor_type="system",
            actor_id="create_api_key",
            actor_role=role,
            event_type="auth.api_key.created",
            outcome="success",
            resource_type="api_key",
            resource_id=key_id,
            metadata={
                "user_id": user.id,
                "key_prefix": key_prefix,
                "key_name": args.name,
            },
            commit=True,
            best_effort=False,
        )

    print("API key created:")
    print(f"  key_id: {key_id}")
    print(f"  key_prefix: {key_prefix}")
    print("  api_key: ")
    print(f"    {raw_key}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_create_key(args))
    except Exception as exc:  # noqa: BLE001 - surface provisioning failures clearly
        print(f"create_api_key failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
