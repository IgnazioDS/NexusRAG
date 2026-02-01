from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.persistence.db import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session() as session:
        yield session
