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
        created = await client.post("/v1/admin/compliance/snapshot", headers=headers)
        assert created.status_code == 200
        snapshot_id = created.json()["data"]["id"]

        listed = await client.get("/v1/admin/compliance/snapshots?limit=5", headers=headers)
        assert listed.status_code == 200
        assert any(row["id"] == snapshot_id for row in listed.json()["data"])

        bundle = await client.get(f"/v1/admin/compliance/bundle/{snapshot_id}.zip", headers=headers)
        assert bundle.status_code == 200
        assert bundle.headers["content-type"] == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(bundle.content))
    names = set(archive.namelist())
    assert "snapshot.json" in names
    assert "controls.json" in names
    assert "config_sanitized.json" in names
    config_payload = json.loads(archive.read("config_sanitized.json").decode("utf-8"))
    assert config_payload["openai_api_key"] == "[REDACTED]"

    get_settings.cache_clear()
