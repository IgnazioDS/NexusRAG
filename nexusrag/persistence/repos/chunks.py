from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import Chunk


async def list_chunks(session: AsyncSession, corpus_id: str) -> list[Chunk]:
    result = await session.execute(select(Chunk).where(Chunk.corpus_id == corpus_id))
    return list(result.scalars().all())
