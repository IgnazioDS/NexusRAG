from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4


ROLE_ORDER: dict[str, int] = {
    "reader": 1,
    "editor": 2,
    "admin": 3,
}


def normalize_role(role: str) -> str:
    # Enforce a stable, lowercased role vocabulary for RBAC checks.
    normalized = role.strip().lower()
    if normalized not in ROLE_ORDER:
        raise ValueError(f"Unsupported role: {role}")
    return normalized


def role_allows(*, role: str, minimum_role: str) -> bool:
    # Compare roles using numeric ordering for least-privilege enforcement.
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(minimum_role, 0)


def hash_api_key(raw_key: str) -> str:
    # Use SHA-256 for deterministic, non-reversible key storage.
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key(*, key_id: str | None = None) -> tuple[str, str, str, str]:
    # Embed the key id in the token so operators can trace secrets safely.
    resolved_id = key_id or uuid4().hex
    secret = secrets.token_urlsafe(32)
    raw_key = f"nrgk_{resolved_id}_{secret}"
    key_prefix = raw_key[:12]
    return resolved_id, raw_key, key_prefix, hash_api_key(raw_key)
