from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from uuid import uuid4
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import ComplianceSnapshot
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_compliance_evaluate_and_list() -> None:
    tenant_id = f"t-compliance-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/admin/compliance/evaluate",
            headers=headers,
            json={"window_days": 30},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["evaluated"] > 0

        list_resp = await client.get("/v1/admin/compliance/evaluations?limit=5", headers=headers)
        assert list_resp.status_code == 200
        evaluations = list_resp.json()["data"]
        assert len(evaluations) >= 1


@pytest.mark.asyncio
async def test_compliance_bundle_generate_and_verify(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "test-signing-key")
    monkeypatch.setenv("COMPLIANCE_SIGNATURE_REQUIRED", "true")
    monkeypatch.setenv("COMPLIANCE_EVIDENCE_DIR", str(tmp_path))
    get_settings.cache_clear()

    tenant_id = f"t-compliance-bundle-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        period_end = _utc_now()
        period_start = period_end - timedelta(days=7)
        resp = await client.post(
            "/v1/admin/compliance/bundles",
            headers=headers,
            json={
                "bundle_type": "soc2_on_demand",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        assert resp.status_code == 200
        bundle = resp.json()["data"]
        assert bundle["status"] == "ready"

        verify = await client.post(
            f"/v1/admin/compliance/bundles/{bundle['id']}/verify",
            headers=headers,
        )
        assert verify.status_code == 200
        assert verify.json()["data"]["verified"] is True

        # Tamper with bundle payload to ensure verification fails.
        bundle_path = Path(bundle["manifest_uri"])
        with bundle_path.open("r+b") as handle:
            handle.seek(0)
            handle.write(b"X")

        verify_failed = await client.post(
            f"/v1/admin/compliance/bundles/{bundle['id']}/verify",
            headers=headers,
        )
        assert verify_failed.status_code == 400
        assert verify_failed.json()["error"]["code"] == "COMPLIANCE_BUNDLE_VERIFY_FAILED"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_compliance_ops_status() -> None:
    tenant_id = f"t-compliance-status-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/ops/compliance/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "controls_passed" in data
        assert "status" in data


@pytest.mark.asyncio
async def test_compliance_snapshot_and_bundle_redacts_config(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-value")
    get_settings.cache_clear()
    tenant_id = f"t-compliance-snapshot-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/v1/admin/compliance/snapshots", headers=headers)
        assert created.status_code == 200
        created_payload = created.json()["data"]
        snapshot_id = created_payload["id"]
        assert created_payload["captured_at"]
        assert "results_json" in created_payload

        listed = await client.get("/v1/admin/compliance/snapshots?limit=5", headers=headers)
        assert listed.status_code == 200
        assert any(row["id"] == snapshot_id for row in listed.json()["data"])

        bundle = await client.get(f"/v1/admin/compliance/snapshots/{snapshot_id}/download", headers=headers)
        assert bundle.status_code == 200
        assert bundle.headers["content-type"] == "application/zip"

        after_bundle = await client.get(f"/v1/admin/compliance/snapshots/{snapshot_id}", headers=headers)
        assert after_bundle.status_code == 200
        artifact_paths = after_bundle.json()["data"]["artifact_paths_json"]
        assert artifact_paths["bundle_download_path"].endswith(f"/v1/admin/compliance/snapshots/{snapshot_id}/download")
        assert artifact_paths["bundle_path"]

    archive = zipfile.ZipFile(io.BytesIO(bundle.content))
    names = set(archive.namelist())
    assert "snapshot.json" in names
    assert "controls.json" in names
    assert "config_sanitized.json" in names
    assert "perf_report_summary.md" in names
    assert "ops_metrics_24h_summary.json" in names
    config_payload = json.loads(archive.read("config_sanitized.json").decode("utf-8"))
    assert config_payload["openai_api_key"] == "[REDACTED]"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_compliance_snapshot_backward_compatibility_for_legacy_rows() -> None:
    tenant_id = f"t-compliance-legacy-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")
    legacy_id = uuid4().hex
    legacy_now = _utc_now()
    async with SessionLocal() as session:
        # Insert a legacy-shaped row (no captured_at/results/artifacts) to verify API fallback behavior.
        session.add(
            ComplianceSnapshot(
                id=legacy_id,
                tenant_id=tenant_id,
                captured_at=None,
                created_at=legacy_now,
                created_by="legacy-test",
                status="pass",
                results_json=None,
                summary_json={"status": "pass", "counts": {"pass": 1, "degraded": 0, "fail": 0}},
                controls_json=[{"control_id": "CC6.1", "status": "pass"}],
                artifact_paths_json=None,
            )
        )
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/v1/admin/compliance/snapshots/{legacy_id}", headers=headers)
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["captured_at"]
        assert payload["results_json"]["summary"]["status"] == "pass"
        assert payload["artifact_paths_json"] == {}
