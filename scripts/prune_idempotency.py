from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete

from nexusrag.domain.models import IdempotencyRecord
from nexusrag.persistence.db import SessionLocal


async def prune() -> None:
    # Remove expired idempotency records to keep storage bounded.
    async with SessionLocal() as session:
        result = await session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < datetime.now(timezone.utc))
        )
        await session.commit()
        deleted = result.rowcount or 0
        print(f"pruned_idempotency_records={deleted}")


if __name__ == "__main__":
    asyncio.run(prune())
