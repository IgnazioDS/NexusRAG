from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import Checkpoint


async def add_checkpoint(session: AsyncSession, session_id: str, state_json: dict) -> Checkpoint:
    checkpoint = Checkpoint(session_id=session_id, state_json=state_json)
    session.add(checkpoint)
    return checkpoint
