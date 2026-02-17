from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexusrag.core.config import get_settings


settings = get_settings()
_engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
# Configure bounded asyncpg pools for predictable latency under load.
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs["pool_size"] = max(1, int(settings.api_db_pool_size))
    _engine_kwargs["max_overflow"] = max(0, int(settings.api_db_max_overflow))
    _engine_kwargs["pool_timeout"] = 30
    _engine_kwargs["pool_recycle"] = 1800
    if settings.api_db_statement_timeout_ms > 0:
        _engine_kwargs["connect_args"] = {
            "server_settings": {"statement_timeout": str(int(settings.api_db_statement_timeout_ms))}
        }
engine = create_async_engine(settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


def pool_stats() -> dict[str, int | None]:
    # Expose DB pool counters for ops/perf visibility without querying Postgres internals.
    pool = engine.sync_engine.pool
    checked_out_fn = getattr(pool, "checkedout", None)
    checked_in_fn = getattr(pool, "checkedin", None)
    overflow_fn = getattr(pool, "overflow", None)
    size_fn = getattr(pool, "size", None)
    return {
        "size": int(size_fn()) if callable(size_fn) else None,
        "checked_out": int(checked_out_fn()) if callable(checked_out_fn) else None,
        "checked_in": int(checked_in_fn()) if callable(checked_in_fn) else None,
        "overflow": int(overflow_fn()) if callable(overflow_fn) else None,
    }
