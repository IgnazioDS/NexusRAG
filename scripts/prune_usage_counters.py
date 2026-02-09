from __future__ import annotations

import asyncio

from nexusrag.persistence.db import SessionLocal
from nexusrag.services.maintenance import prune_usage_counters


async def prune() -> None:
    async with SessionLocal() as session:
        deleted = await prune_usage_counters(session)
        await session.commit()
        print(f"pruned_usage_counters={deleted}")


if __name__ == "__main__":
    asyncio.run(prune())
