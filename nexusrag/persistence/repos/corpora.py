from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import Corpus


async def get_corpus(session: AsyncSession, corpus_id: str) -> Corpus | None:
    result = await session.execute(select(Corpus).where(Corpus.id == corpus_id))
    return result.scalar_one_or_none()
