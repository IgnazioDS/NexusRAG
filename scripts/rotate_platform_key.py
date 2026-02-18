from __future__ import annotations

import argparse
import asyncio
import sys

from nexusrag.persistence.db import SessionLocal
from nexusrag.services.security import rotate_platform_key


def _build_parser() -> argparse.ArgumentParser:
    # Keep purpose explicit so local rotations never default to an unexpected key class.
    parser = argparse.ArgumentParser(description="Rotate a platform keyring key")
    parser.add_argument(
        "--purpose",
        required=True,
        help="signing|encryption|backup_signing|backup_encryption|webhook_signing",
    )
    return parser


async def _rotate(purpose: str) -> int:
    # Rotate exactly one purpose at a time to preserve single-active-key invariants.
    async with SessionLocal() as session:
        key, secret, replaced_key_id = await rotate_platform_key(session, purpose=purpose)
    print("Platform key rotated:")
    print(f"  key_id: {key.key_id}")
    print(f"  purpose: {key.purpose}")
    print(f"  replaced_key_id: {replaced_key_id or ''}")
    print("  secret:")
    print(f"    {secret}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_rotate(args.purpose))
    except Exception as exc:  # noqa: BLE001 - surface operational failures in CLI output.
        print(f"rotate_platform_key failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
