from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.persistence.db import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # One AsyncSession per request; context manager ensures close on success/error.
    async with get_session() as session:
        yield session


async def get_tenant_id(x_tenant_id: str | None = Header(default=None)) -> str:
    # Temporary tenant scoping until auth is implemented; keep it explicit and required.
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header is required")
    return x_tenant_id
