from __future__ import annotations

import gzip
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    AuditEvent,
    Corpus,
    Document,
    EncryptedBlob,
    KeyRotationJob,
    Message,
    Session as SessionRow,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_session(tenant_id: str, session_id: str) -> None:
    async with SessionLocal() as session:
        session.add(SessionRow(id=session_id, tenant_id=tenant_id))
        await session.flush()
        session.add(Message(session_id=session_id, role="user", content="hello"))
        await session.commit()


async def _seed_document(tenant_id: str, document_id: str, corpus_id: str) -> None:
    async with SessionLocal() as session:
        session.add(Corpus(id=corpus_id, tenant_id=tenant_id, name="Crypto Corpus", provider_config_json={}))
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
                created_at=_now_utc() - timedelta(days=2),
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_dsar_export_creates_encrypted_blob_and_download_audit() -> None:
    tenant_id = f"t-crypto-dsar-{uuid4().hex}"
    session_id = f"s-crypto-{uuid4().hex}"
    await _seed_session(tenant_id, session_id)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/admin/governance/dsar",
            headers=headers,
            json={
                "request_type": "export",
                "subject_type": "session",
                "subject_id": session_id,
                "reason": "export",
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        dsar_id = data["id"]
        assert data["artifact_uri"].startswith("encrypted_blob:")

        artifact_resp = await client.get(f"/v1/admin/governance/dsar/{dsar_id}/artifact", headers=headers)
        assert artifact_resp.status_code == 200
        assert artifact_resp.headers["content-type"] == "application/gzip"
        # Ensure payload is gzip-readable.
        assert gzip.decompress(artifact_resp.content)

    async with SessionLocal() as session:
        blob = (
            await session.execute(
                select(EncryptedBlob).where(
                    EncryptedBlob.tenant_id == tenant_id,
                    EncryptedBlob.resource_type == "dsar_artifact",
                    EncryptedBlob.resource_id == str(dsar_id),
                )
            )
        ).scalar_one_or_none()
        assert blob is not None
        audit = (
            await session.execute(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.event_type == "crypto.decrypt.accessed",
                )
                .order_by(AuditEvent.occurred_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        assert audit is not None


@pytest.mark.asyncio
async def test_rotate_key_and_reencrypt_job_completes() -> None:
    tenant_id = f"t-crypto-rotate-{uuid4().hex}"
    session_id = f"s-crypto-rotate-{uuid4().hex}"
    await _seed_session(tenant_id, session_id)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/admin/governance/dsar",
            headers=headers,
            json={
                "request_type": "export",
                "subject_type": "session",
                "subject_id": session_id,
                "reason": "export",
            },
        )
        assert resp.status_code == 200

        rotate = await client.post(
            f"/v1/admin/crypto/keys/{tenant_id}/rotate",
            headers=headers,
            json={"reason": "rotate", "reencrypt": True, "force": False},
        )
        assert rotate.status_code == 200
        payload = rotate.json()["data"]
        assert payload["rotation_job"] is not None
        assert payload["rotation_job"]["status"] in {"completed", "failed"}


@pytest.mark.asyncio
async def test_concurrent_rotation_blocked() -> None:
    tenant_id = f"t-crypto-block-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    async with SessionLocal() as session:
        job = KeyRotationJob(
            tenant_id=tenant_id,
            from_key_id=1,
            to_key_id=2,
            status="running",
            total_items=0,
            processed_items=0,
            failed_items=0,
        )
        session.add(job)
        await session.commit()

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        rotate = await client.post(
            f"/v1/admin/crypto/keys/{tenant_id}/rotate",
            headers=headers,
            json={"reason": "rotate", "reencrypt": True, "force": False},
        )
        assert rotate.status_code == 409
        assert rotate.json()["error"]["code"] == "KEY_ROTATION_IN_PROGRESS"


@pytest.mark.asyncio
async def test_kms_unavailable_blocks_sensitive_writes(monkeypatch) -> None:
    monkeypatch.setenv("CRYPTO_PROVIDER", "aws_kms")
    monkeypatch.setenv("CRYPTO_ENABLED", "true")
    monkeypatch.setenv("CRYPTO_FAIL_MODE", "closed")
    monkeypatch.setenv("CRYPTO_REQUIRE_ENCRYPTION_FOR_SENSITIVE", "true")
    get_settings.cache_clear()

    tenant_id = f"t-crypto-kms-{uuid4().hex}"
    session_id = f"s-crypto-kms-{uuid4().hex}"
    await _seed_session(tenant_id, session_id)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(tenant_id=tenant_id, role="admin")

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/admin/governance/dsar",
            headers=headers,
            json={
                "request_type": "export",
                "subject_type": "session",
                "subject_id": session_id,
                "reason": "export",
            },
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] in {"KMS_UNAVAILABLE", "ENCRYPTION_REQUIRED"}

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_policy_require_encryption_blocks_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("CRYPTO_ENABLED", "false")
    monkeypatch.setenv("CRYPTO_FAIL_MODE", "closed")
    monkeypatch.setenv("CRYPTO_REQUIRE_ENCRYPTION_FOR_SENSITIVE", "true")
    get_settings.cache_clear()

    tenant_id = f"t-crypto-policy-{uuid4().hex}"
    document_id = f"d-crypto-policy-{uuid4().hex}"
    corpus_id = f"c-crypto-policy-{uuid4().hex}"
    await _seed_document(tenant_id, document_id, corpus_id)
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
                "action_json": {"type": "require_encryption"},
            },
        )
        assert policy_resp.status_code == 200

        blocked = await client.delete(f"/v1/documents/{document_id}", headers=headers)
        assert blocked.status_code == 503
        assert blocked.json()["error"]["code"] == "ENCRYPTION_REQUIRED"

    get_settings.cache_clear()
