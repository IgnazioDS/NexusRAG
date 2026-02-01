from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.errors import DatabaseError, SessionTenantMismatchError
from nexusrag.domain.models import Session


async def get_session(session: AsyncSession, session_id: str) -> Session | None:
    result = await session.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def upsert_session(session: AsyncSession, session_id: str, tenant_id: str) -> Session:
    existing = await get_session(session, session_id)
    if existing:
        # Security invariant: never mutate tenant_id for an existing session.
        if existing.tenant_id != tenant_id:
            raise SessionTenantMismatchError("session tenant_id does not match")
        await session.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(last_seen_at=datetime.utcnow())
        )
        return existing

    # Race-safe insert: if another request creates the session first, reload instead.
    stmt = insert(Session).values(id=session_id, tenant_id=tenant_id)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Session.id])
    try:
        await session.execute(stmt)
    except IntegrityError:
        # Concurrency can still raise integrity errors; rollback and reload.
        await session.rollback()

    created = await get_session(session, session_id)
    if created is None:
        raise DatabaseError("session insert failed unexpectedly")
    if created.tenant_id != tenant_id:
        raise SessionTenantMismatchError("session tenant_id does not match")

    await session.execute(
        update(Session)
        .where(Session.id == session_id)
        .values(last_seen_at=datetime.utcnow())
    )
    return created
