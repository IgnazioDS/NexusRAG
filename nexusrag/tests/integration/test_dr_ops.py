from __future__ import annotations

import asyncio
import gzip
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import AuditEvent, BackupJob, RestoreDrill
from nexusrag.persistence.db import SessionLocal
from nexusrag.services import backup as backup_service
from nexusrag.tests.utils.auth import create_test_api_key


async def _wait_for_backup(job_id: int) -> BackupJob:
    # Poll for background backup completion to keep tests deterministic.
    for _ in range(50):
        async with SessionLocal() as session:
            job = await session.get(BackupJob, job_id)
            if job and job.status in {"succeeded", "failed"}:
                return job
        await asyncio.sleep(0.1)
    raise AssertionError("backup job did not complete in time")


async def _wait_for_restore_drill(drill_id: int) -> RestoreDrill:
    # Poll for restore drill completion to keep tests deterministic.
    for _ in range(50):
        async with SessionLocal() as session:
            drill = await session.get(RestoreDrill, drill_id)
            if drill and drill.status in {"passed", "failed"}:
                return drill
        await asyncio.sleep(0.1)
    raise AssertionError("restore drill did not complete in time")


def _fake_dump(component: backup_service.BackupComponent, output_path: Path, _db_url: str) -> None:
    # Produce a small gzipped payload to avoid pg_dump in tests.
    with gzip.open(output_path, "wb") as handle:
        handle.write(component.encode("utf-8"))


@pytest.mark.asyncio
async def test_dr_backup_and_restore_drill(monkeypatch, tmp_path: Path) -> None:
    # Validate DR backup, list, and restore drill flows end-to-end.
    monkeypatch.setenv("BACKUP_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "00" * 32)
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "test-signing-key")
    monkeypatch.setenv("BACKUP_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("BACKUP_SIGNING_ENABLED", "true")
    monkeypatch.setenv("RESTORE_REQUIRE_SIGNATURE", "true")
    get_settings.cache_clear()

    monkeypatch.setattr(backup_service, "get_dump_runner", lambda: _fake_dump)

    app = create_app()
    transport = ASGITransport(app=app)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id="t-dr", role="admin")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/ops/dr/backup", headers=headers)
        assert response.status_code == 200
        payload = response.json()["data"]
        job_id = payload["job_id"]

    job = await _wait_for_backup(job_id)
    assert job.status == "succeeded"
    assert job.manifest_uri is not None
    assert Path(job.manifest_uri).exists()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/ops/dr/backups", headers=headers)
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["items"]

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/ops/dr/restore-drill", headers=headers)
        assert response.status_code == 200
        payload = response.json()["data"]
        drill_id = payload["drill_id"]

    drill = await _wait_for_restore_drill(drill_id)
    assert drill.status == "passed"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/ops/dr/readiness", headers=headers)
        assert response.status_code == 200
        readiness = response.json()["data"]
        assert readiness["backup"]["last_status"] in {"succeeded", "failed", "unknown"}
        assert readiness["status"] in {"ready", "at_risk", "not_ready"}

    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == "t-dr",
                    AuditEvent.event_type.in_(["dr.backup.succeeded", "dr.restore_drill.passed"]),
                )
            )
        ).scalars().all()
        assert events
    get_settings.cache_clear()
