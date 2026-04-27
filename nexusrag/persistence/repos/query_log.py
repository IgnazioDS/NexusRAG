"""Read/write helpers for the query_log table.

Insertion happens fire-and-forget from the FastAPI middleware so the
response path never blocks on the telemetry write. Reads happen on every
/api/stats request and use windowed aggregations indexed on completed_at.

Privacy invariant: query_log NEVER stores prompt text, model output,
tenant identifiers, or user identifiers. Only the aggregate-friendly
fields (id, started_at, completed_at, latency_ms, retrieved_chunks,
status) are persisted. The /api/stats endpoint never returns row-level
data — only counts and percentiles.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import Chunk, QueryLog


@dataclass(frozen=True)
class QueryAggregates:
    queries_total: int
    queries_24h: int
    queries_7d: int
    p50_latency_ms: int | None
    p95_latency_ms: int | None
    avg_retrieval_size: int
    indexed_chunks: int
    last_active_at: datetime | None


# --- safety caps per the public schema ---
SAFETY_CAPS: dict[str, int] = {
    "queries_total": 10_000_000,
    "queries_24h": 1_000_000,
    "queries_7d": 7_000_000,
    "p50_latency_ms": 600_000,  # 10 min sanity cap
    "p95_latency_ms": 600_000,
    "avg_retrieval_size": 10_000,
    "indexed_chunks": 100_000_000,
}


def _cap(name: str, value: int) -> int:
    cap = SAFETY_CAPS.get(name)
    return min(value, cap) if cap is not None else value


async def record_query(
    session: AsyncSession,
    *,
    query_id: UUID,
    started_at: datetime,
    completed_at: datetime,
    retrieved_chunks: int,
    status: str,
) -> None:
    """Insert one query_log row. Latency is computed at insert time."""
    delta = completed_at - started_at
    latency_ms = int(delta.total_seconds() * 1000)
    if latency_ms < 0:
        # Clock skew on a request straddling worker boundaries; clamp to zero.
        latency_ms = 0
    row = QueryLog(
        query_id=query_id,
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=latency_ms,
        retrieved_chunks=max(0, retrieved_chunks),
        status=status if status in {"ok", "error", "cancelled"} else "error",
    )
    session.add(row)
    await session.commit()


async def aggregate(session: AsyncSession) -> QueryAggregates:
    """Compute the public Tier-A aggregates in a small set of queries.

    Each scalar query is cheap given the descending index on completed_at.
    We deliberately avoid a single mega-CTE so a transient failure in any
    one rollup doesn't blow up the whole response.
    """
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    # Total count, all-time.
    queries_total_result = await session.execute(select(func.count()).select_from(QueryLog))
    queries_total = int(queries_total_result.scalar() or 0)

    # 24h window.
    queries_24h_result = await session.execute(
        select(func.count())
        .select_from(QueryLog)
        .where(QueryLog.completed_at >= cutoff_24h)
    )
    queries_24h = int(queries_24h_result.scalar() or 0)

    # 7d window.
    queries_7d_result = await session.execute(
        select(func.count())
        .select_from(QueryLog)
        .where(QueryLog.completed_at >= cutoff_7d)
    )
    queries_7d = int(queries_7d_result.scalar() or 0)

    # p50 + p95 latency over the 24h window. Use percentile_cont via raw SQL
    # because SQLAlchemy's Core lacks first-class percentile expressions.
    pct_result = await session.execute(
        text(
            """
            SELECT
              percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
              percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
            FROM query_log
            WHERE completed_at >= :cutoff
            """
        ),
        {"cutoff": cutoff_24h},
    )
    pct_row = pct_result.first()
    p50_latency_ms = int(pct_row.p50) if pct_row and pct_row.p50 is not None else None
    p95_latency_ms = int(pct_row.p95) if pct_row and pct_row.p95 is not None else None

    # Average retrieval size, 24h window. Round to int per the public schema.
    avg_result = await session.execute(
        select(func.avg(QueryLog.retrieved_chunks))
        .where(QueryLog.completed_at >= cutoff_24h)
    )
    avg_raw = avg_result.scalar()
    avg_retrieval_size = int(round(float(avg_raw))) if avg_raw is not None else 0

    # Vector index size. Read on the same path so a healthy /api/stats
    # response confirms both the telemetry table and the vector store.
    chunks_result = await session.execute(select(func.count()).select_from(Chunk))
    indexed_chunks = int(chunks_result.scalar() or 0)

    # Most recent successful query (powers Tier-A `last_active_at`).
    last_active_result = await session.execute(
        select(func.max(QueryLog.completed_at)).where(QueryLog.status == "ok")
    )
    last_active_at = last_active_result.scalar()

    return QueryAggregates(
        queries_total=_cap("queries_total", queries_total),
        queries_24h=_cap("queries_24h", queries_24h),
        queries_7d=_cap("queries_7d", queries_7d),
        p50_latency_ms=_cap("p50_latency_ms", p50_latency_ms) if p50_latency_ms is not None else None,
        p95_latency_ms=_cap("p95_latency_ms", p95_latency_ms) if p95_latency_ms is not None else None,
        avg_retrieval_size=_cap("avg_retrieval_size", avg_retrieval_size),
        indexed_chunks=_cap("indexed_chunks", indexed_chunks),
        last_active_at=last_active_at,
    )


def to_metrics_dict(agg: QueryAggregates) -> dict[str, Any]:
    """Render the aggregates into the public Tier-A `metrics` payload."""
    return {
        "queries_total": agg.queries_total,
        "queries_24h": agg.queries_24h,
        "queries_7d": agg.queries_7d,
        "p50_latency_ms": agg.p50_latency_ms if agg.p50_latency_ms is not None else 0,
        "p95_latency_ms": agg.p95_latency_ms if agg.p95_latency_ms is not None else 0,
        "avg_retrieval_size": agg.avg_retrieval_size,
        "indexed_chunks": agg.indexed_chunks,
    }


def zero_metrics() -> dict[str, Any]:
    """Fallback used when the database is unreachable. Contract stays valid."""
    return {
        "queries_total": 0,
        "queries_24h": 0,
        "queries_7d": 0,
        "p50_latency_ms": 0,
        "p95_latency_ms": 0,
        "avg_retrieval_size": 0,
        "indexed_chunks": 0,
    }
