from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import secrets
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import PlatformKey


_ALLOWED_PURPOSES = {
    "signing",
    "encryption",
    "backup_signing",
    "backup_encryption",
    "webhook_signing",
}
_ALLOWED_STATUSES = {"active", "retiring", "retired", "revoked"}


class KeyringConfigurationError(RuntimeError):
    """Raised when required keyring encryption config is missing or invalid."""


class KeyringDisabledError(RuntimeError):
    """Raised when keyring encryption is explicitly optional but currently unavailable."""


@dataclass(frozen=True)
class PlatformKeyView:
    key_id: str
    purpose: str
    status: str
    created_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_fernet() -> Fernet:
    settings = get_settings()
    # Enforce explicit keyring configuration in required mode; never fall back to plaintext storage paths.
    source = (settings.keyring_master_key or "").strip()
    if not source:
        if settings.keyring_master_key_required:
            raise KeyringConfigurationError("KEYRING_MASTER_KEY is required for keyring encryption")
        # Optional mode allows local/dev runs without keyring encryption capabilities.
        fallback = (settings.crypto_local_master_key or "").strip()
        if not fallback:
            raise KeyringDisabledError("KEYRING_MASTER_KEY is not configured and keyring is disabled")
        source = fallback
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return Fernet(urlsafe_b64encode(digest))


def _encrypt_secret(secret: str) -> str:
    # Normalize cryptography return types to a concrete string for persistence typing.
    token = _build_fernet().encrypt(secret.encode("utf-8"))
    return str(token.decode("utf-8"))


def _new_key_id(purpose: str) -> str:
    prefix_map = {
        "signing": "sig",
        "encryption": "enc",
        "backup_signing": "bksig",
        "backup_encryption": "bkenc",
        "webhook_signing": "whsig",
    }
    prefix = prefix_map.get(purpose, "key")
    return f"{prefix}_{uuid4().hex}"


def _to_view(row: PlatformKey) -> PlatformKeyView:
    return PlatformKeyView(
        key_id=row.key_id,
        purpose=row.purpose,
        status=row.status,
        created_at=row.created_at,
        activated_at=row.activated_at,
        retired_at=row.retired_at,
    )


def _validate_purpose(purpose: str) -> str:
    normalized = purpose.strip().lower()
    if normalized not in _ALLOWED_PURPOSES:
        raise ValueError("Unsupported key purpose")
    return normalized


async def list_platform_keys(
    session: AsyncSession,
    *,
    purpose: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[PlatformKeyView]:
    # Keep list queries bounded for deterministic admin API latency.
    query = select(PlatformKey)
    if purpose is not None:
        query = query.where(PlatformKey.purpose == _validate_purpose(purpose))
    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in _ALLOWED_STATUSES:
            raise ValueError("Unsupported key status")
        query = query.where(PlatformKey.status == normalized_status)
    rows = (
        await session.execute(
            query.order_by(PlatformKey.created_at.desc()).limit(max(1, min(limit, 200)))
        )
    ).scalars().all()
    return [_to_view(row) for row in rows]


async def rotate_platform_key(
    session: AsyncSession,
    *,
    purpose: str,
) -> tuple[PlatformKeyView, str, str | None]:
    # Rotation creates a fresh active key and retires only the currently-active key for that purpose.
    resolved_purpose = _validate_purpose(purpose)
    existing_active = (
        await session.execute(
            select(PlatformKey)
            .where(PlatformKey.purpose == resolved_purpose, PlatformKey.status == "active")
            .order_by(PlatformKey.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        # Use retiring as an intermediate lifecycle marker for explicit retirement workflows.
        existing_active.status = "retiring"
        existing_active.retired_at = _utc_now()

    raw_secret = secrets.token_urlsafe(48)
    new_key = PlatformKey(
        key_id=_new_key_id(resolved_purpose),
        purpose=resolved_purpose,
        status="active",
        secret_ciphertext=_encrypt_secret(raw_secret),
        activated_at=_utc_now(),
    )
    session.add(new_key)
    await session.commit()
    await session.refresh(new_key)
    return _to_view(new_key), raw_secret, existing_active.key_id if existing_active else None


async def retire_platform_key(
    session: AsyncSession,
    *,
    key_id: str,
) -> PlatformKeyView | None:
    # Retire is idempotent and never deletes historical key metadata used for audits.
    row = await session.get(PlatformKey, key_id)
    if row is None:
        return None
    if row.status in {"active", "retiring"}:
        row.status = "retired"
        row.retired_at = _utc_now()
        await session.commit()
        await session.refresh(row)
    return _to_view(row)
