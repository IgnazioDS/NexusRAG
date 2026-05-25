"""Read/write helpers for the benchmark_runs table."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import BenchmarkRun


async def latest_runs(session: AsyncSession, limit: int = 2) -> list[BenchmarkRun]:
    """Return the most recent benchmark runs, newest first (latest + previous)."""
    result = await session.execute(
        select(BenchmarkRun).order_by(BenchmarkRun.generated_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
