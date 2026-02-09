from __future__ import annotations

import asyncio

from nexusrag.persistence.db import SessionLocal
from nexusrag.services.maintenance import prune_audit_events


async def prune() -> None:
    async with SessionLocal() as session:
        deleted = await prune_audit_events(session)
        await session.commit()
        print(f"pruned_audit_events={deleted}")


if __name__ == "__main__":
    asyncio.run(prune())
