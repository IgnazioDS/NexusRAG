from __future__ import annotations

import asyncio

import pytest

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
