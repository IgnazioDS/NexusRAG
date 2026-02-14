from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Corpus, Document, Session as SessionRow
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_document(tenant_id: str, document_id: str, corpus_id: str, *, age_days: int = 10) -> None:
    # Seed deterministic document rows for retention and policy tests.
    ts = _now_utc() - timedelta(days=age_days)
    async with SessionLocal() as session:
        session.add(Corpus(id=corpus_id, tenant_id=tenant_id, name="Gov Corpus", provider_config_json={}))
        session.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                corpus_id=corpus_id,
                filename="doc.txt",
                content_type="text/plain",
                source="raw_text",
                ingest_source="raw_text",
                storage_path=None,
                metadata_json={},
                status="succeeded",
                created_at=ts,
                updated_at=ts,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_legal_hold_skips_retention_and_release_allows_delete() -> None:
    tenant_id = f"t-gov-{uuid4().hex}"
    document_id = f"d-gov-{uuid4().hex}"
    corpus_id = f"c-gov-{uuid4().hex}"
    await _seed_document(tenant_id, document_id, corpus_id)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        policy_resp = await client.patch(
            "/v1/admin/governance/retention/policy",
            headers=headers,
            json={
                "documents_ttl_days": 1,
                "hard_delete_enabled": True,
                "anonymize_instead_of_delete": False,
            },
        )
        assert policy_resp.status_code == 200

        hold_resp = await client.post(
            "/v1/admin/governance/legal-holds",
            headers=headers,
            json={
                "scope_type": "document",
                "scope_id": document_id,
                "reason": "litigation",
            },
        )
        assert hold_resp.status_code == 200
        hold_id = hold_resp.json()["data"]["id"]

        first_run = await client.post(
            f"/v1/admin/governance/retention/run?tenant_id={tenant_id}",
            headers=headers,
        )
        assert first_run.status_code == 200
        first_report = first_run.json()["data"]["report_json"]
        assert first_report["categories"]["documents"]["skipped_hold"] == 1

        release_resp = await client.post(
            f"/v1/admin/governance/legal-holds/{hold_id}/release",
            headers=headers,
        )
        assert release_resp.status_code == 200

        second_run = await client.post(
            f"/v1/admin/governance/retention/run?tenant_id={tenant_id}",
            headers=headers,
        )
        assert second_run.status_code == 200
        second_report = second_run.json()["data"]["report_json"]
        assert second_report["categories"]["documents"]["deleted"] == 1

    async with SessionLocal() as session:
        row = await session.get(Document, document_id)
    assert row is None


@pytest.mark.asyncio
async def test_dsar_delete_on_hold_is_rejected_and_export_completes() -> None:
    tenant_id = f"t-gov-dsar-{uuid4().hex}"
    document_id = f"d-gov-dsar-{uuid4().hex}"
    corpus_id = f"c-gov-dsar-{uuid4().hex}"
    session_id = f"s-gov-dsar-{uuid4().hex}"
    await _seed_document(tenant_id, document_id, corpus_id)
    async with SessionLocal() as session:
        session.add(SessionRow(id=session_id, tenant_id=tenant_id))
        await session.commit()

    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        hold_resp = await client.post(
            "/v1/admin/governance/legal-holds",
            headers=headers,
            json={"scope_type": "document", "scope_id": document_id, "reason": "hold"},
        )
        assert hold_resp.status_code == 200

        blocked = await client.post(
            "/v1/admin/governance/dsar",
            headers=headers,
            json={
                "request_type": "delete",
                "subject_type": "document",
                "subject_id": document_id,
                "reason": "erase",
            },
        )
        assert blocked.status_code == 200
        blocked_data = blocked.json()["data"]
        assert blocked_data["status"] == "rejected"
        assert blocked_data["error_code"] == "LEGAL_HOLD_ACTIVE"

        exported = await client.post(
            "/v1/admin/governance/dsar",
            headers=headers,
            json={
                "request_type": "export",
                "subject_type": "session",
                "subject_id": session_id,
                "reason": "subject export",
            },
        )
        assert exported.status_code == 200
        exported_data = exported.json()["data"]
        assert exported_data["status"] == "completed"
        assert exported_data["artifact_uri"]
        artifact = Path(exported_data["artifact_uri"])
        assert artifact.exists()
        assert artifact.with_name("manifest.json").exists()


@pytest.mark.asyncio
async def test_policy_deny_blocks_document_delete() -> None:
    tenant_id = f"t-gov-pol-{uuid4().hex}"
    document_id = f"d-gov-pol-{uuid4().hex}"
    corpus_id = f"c-gov-pol-{uuid4().hex}"
    await _seed_document(tenant_id, document_id, corpus_id, age_days=1)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        policy_resp = await client.post(
            "/v1/admin/governance/policies",
            headers=headers,
            json={
                "rule_key": "documents.delete",
                "priority": 1000,
                "condition_json": {"method": "DELETE"},
                "action_json": {"type": "deny", "code": "POLICY_DENIED", "message": "blocked"},
            },
        )
        assert policy_resp.status_code == 200

        blocked = await client.delete(f"/v1/documents/{document_id}", headers=headers)
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "POLICY_DENIED"


@pytest.mark.asyncio
async def test_governance_status_and_evidence_shapes() -> None:
    tenant_id = f"t-gov-ops-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        hold_resp = await client.post(
            "/v1/admin/governance/legal-holds",
            headers=headers,
            json={"scope_type": "tenant", "scope_id": None, "reason": "compliance"},
        )
        assert hold_resp.status_code == 200

        status_resp = await client.get("/v1/ops/governance/status", headers=headers)
        assert status_resp.status_code == 200
        status_data = status_resp.json()["data"]
        assert "active_holds_count" in status_data
        assert "pending_dsar_count" in status_data
        assert "compliance_posture" in status_data

        evidence_resp = await client.get("/v1/ops/governance/evidence?window_days=30", headers=headers)
        assert evidence_resp.status_code == 200
        evidence_data = evidence_resp.json()["data"]
        assert set(evidence_data.keys()) == {
            "retention_runs",
            "dsar_requests",
            "legal_holds",
            "policy_changes",
        }


@pytest.mark.asyncio
async def test_backup_prune_respects_backup_set_hold(monkeypatch, tmp_path) -> None:
    tenant_id = f"t-gov-bkp-{uuid4().hex}"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir = backup_dir / "backup_999"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    old_ts = (_now_utc() - timedelta(days=90)).isoformat()
    manifest_path.write_text(
        json.dumps(
            {
                "backup_id": "999",
                "created_at": old_ts,
                "backup_type": "all",
                "app_version": "1.8.0",
                "manifest_version": "1.0",
                "encryption_enabled": False,
                "signing_enabled": False,
                "components": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACKUP_LOCAL_DIR", str(backup_dir))
    monkeypatch.setenv("BACKUP_RETENTION_DAYS", "1")
    get_settings.cache_clear()

    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        hold_resp = await client.post(
            "/v1/admin/governance/legal-holds",
            headers=headers,
            json={
                "scope_type": "backup_set",
                "scope_id": "999",
                "reason": "hold backup set",
            },
        )
        assert hold_resp.status_code == 200
        run_resp = await client.post(
            "/v1/admin/maintenance/run?task=backup_prune_retention",
            headers=headers,
        )
        assert run_resp.status_code == 200
    assert manifest_dir.exists()

    get_settings.cache_clear()
