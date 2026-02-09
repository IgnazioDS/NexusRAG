from __future__ import annotations

from fastapi import HTTPException


def enforce_key_limit(active_count: int | None, max_active: int) -> None:
    # Enforce tenant-level API key limits with a stable error payload.
    if active_count is None:
        return
    if active_count >= max_active:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "KEY_LIMIT_REACHED",
                "message": "Maximum active API keys reached",
                "max_active": max_active,
            },
        )
