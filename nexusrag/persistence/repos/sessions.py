from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import Session


async def get_session(session: AsyncSession, session_id: str) -> Session | None:
    result = await session.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def upsert_session(session: AsyncSession, session_id: str, tenant_id: str) -> Session:
    existing = await get_session(session, session_id)
    if existing:
        await session.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(last_seen_at=datetime.utcnow())
        )
        return existing

    new_session = Session(id=session_id, tenant_id=tenant_id)
    session.add(new_session)
    return new_session
