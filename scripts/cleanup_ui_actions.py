from __future__ import annotations

import asyncio

from nexusrag.persistence.db import SessionLocal
from nexusrag.services.maintenance import cleanup_ui_actions


async def prune() -> None:
    async with SessionLocal() as session:
        deleted = await cleanup_ui_actions(session)
        await session.commit()
        print(f"pruned_ui_actions={deleted}")


if __name__ == "__main__":
    asyncio.run(prune())
