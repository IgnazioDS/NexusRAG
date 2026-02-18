from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from nexusrag.domain.models import (
    ComplianceArtifact,
    DsarRequest,
    EncryptedBlob,
    FailoverClusterState,
    FailoverEvent,
    FailoverToken,
    GovernanceRetentionRun,
    ComplianceSnapshot,
    ControlEvaluation,
    EvidenceBundle,
    KeyRotationJob,
    LegalHold,
    NotificationAttempt,
    NotificationJob,
    OpsIncident,
    IncidentTimelineEvent,
    AlertEvent,
    AlertRule,
    PlatformKey,
    PolicyRule,
    RegionStatus,
    RetentionRun,
    RetentionPolicy,
    TenantKey,
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
    # Keep control-plane and governance state isolated across tests for determinism.
    try:
        async with SessionLocal() as session:
            await session.execute(delete(DsarRequest))
            await session.execute(delete(GovernanceRetentionRun))
            await session.execute(delete(LegalHold))
            await session.execute(delete(PolicyRule))
            await session.execute(delete(RetentionPolicy))
            await session.execute(delete(EncryptedBlob))
            await session.execute(delete(ComplianceArtifact))
            await session.execute(delete(ComplianceSnapshot))
            await session.execute(delete(ControlEvaluation))
            await session.execute(delete(EvidenceBundle))
            await session.execute(delete(NotificationAttempt))
            await session.execute(delete(NotificationJob))
            await session.execute(delete(IncidentTimelineEvent))
            await session.execute(delete(OpsIncident))
            await session.execute(delete(AlertEvent))
            await session.execute(delete(AlertRule))
            await session.execute(delete(RetentionRun))
            await session.execute(delete(PlatformKey))
            await session.execute(delete(KeyRotationJob))
            await session.execute(delete(TenantKey))
            await session.execute(delete(FailoverEvent))
            await session.execute(delete(FailoverToken))
            await session.execute(delete(RegionStatus))
            await session.execute(delete(FailoverClusterState))
            await session.commit()
    except SQLAlchemyError:
        # Tolerate pre-migration test DBs where failover tables may not exist yet.
        pass
    yield
