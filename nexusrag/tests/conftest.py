from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from nexusrag.domain.models import (
    FailoverClusterState,
    FailoverEvent,
    FailoverToken,
    RegionStatus,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.persistence.db import engine


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    # Use a session-wide loop so asyncpg connections stay bound to one loop.
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def dispose_engine_between_tests() -> None:
    # Dispose the async engine to prevent cross-loop connection reuse between tests.
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def reset_failover_tables_between_tests() -> None:
    # Keep failover control-plane state isolated so write-freeze does not leak across tests.
    try:
        async with SessionLocal() as session:
            await session.execute(delete(FailoverEvent))
            await session.execute(delete(FailoverToken))
            await session.execute(delete(RegionStatus))
            await session.execute(delete(FailoverClusterState))
            await session.commit()
    except SQLAlchemyError:
        # Tolerate pre-migration test DBs where failover tables may not exist yet.
        pass
    yield
