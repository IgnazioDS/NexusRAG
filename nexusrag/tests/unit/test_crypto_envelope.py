from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nexusrag.core.config import get_settings
from nexusrag.domain.models import EncryptedBlob, TenantKey
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.crypto.envelope import EnvelopeResult, decrypt_payload, encrypt_payload
from nexusrag.services.crypto.kms.local import LocalKmsProvider
from nexusrag.services.crypto.service import create_rotation_job, get_active_key, rotate_key, run_rotation_job, store_encrypted_blob


def _set_crypto_env(monkeypatch) -> None:
    monkeypatch.setenv("CRYPTO_ENABLED", "true")
    monkeypatch.setenv("CRYPTO_PROVIDER", "local_kms")
    monkeypatch.setenv("CRYPTO_LOCAL_MASTER_KEY", "00" * 32)
    monkeypatch.setenv("CRYPTO_REQUIRE_ENCRYPTION_FOR_SENSITIVE", "true")
    get_settings.cache_clear()


def test_envelope_roundtrip_and_aad_mismatch(monkeypatch) -> None:
    _set_crypto_env(monkeypatch)
    provider = LocalKmsProvider()
    key_ref = provider.build_key_ref(tenant_id="t1", key_alias="tenant-master", key_version=1)
    payload = b"hello"
    result = encrypt_payload(
        tenant_id="t1",
        resource_type="dsar_artifact",
        resource_id="r1",
        plaintext=payload,
        key_ref=key_ref,
        key_version=1,
        provider=provider.provider,
        created_at=datetime.now(timezone.utc),
    )
    assert decrypt_payload(result, tenant_id="t1") == payload

    tampered = EnvelopeResult(
        wrapped_dek=result.wrapped_dek,
        key_ref=result.key_ref,
        key_version=result.key_version,
        provider=result.provider,
        nonce=result.nonce,
        tag=result.tag,
        cipher_text=result.cipher_text,
        aad_json={**result.aad_json, "tenant_id": "t2"},
        checksum_sha256=result.checksum_sha256,
    )
    with pytest.raises(Exception):
        decrypt_payload(tampered, tenant_id="t1")


def test_checksum_mismatch_detected(monkeypatch) -> None:
    _set_crypto_env(monkeypatch)
    provider = LocalKmsProvider()
    key_ref = provider.build_key_ref(tenant_id="t1", key_alias="tenant-master", key_version=1)
    payload = b"payload"
    result = encrypt_payload(
        tenant_id="t1",
        resource_type="dsar_artifact",
        resource_id="r2",
        plaintext=payload,
        key_ref=key_ref,
        key_version=1,
        provider=provider.provider,
        created_at=datetime.now(timezone.utc),
    )
    tampered = EnvelopeResult(
        wrapped_dek=result.wrapped_dek,
        key_ref=result.key_ref,
        key_version=result.key_version,
        provider=result.provider,
        nonce=result.nonce,
        tag=result.tag,
        cipher_text=result.cipher_text,
        aad_json=result.aad_json,
        checksum_sha256="deadbeef",
    )
    with pytest.raises(Exception):
        decrypt_payload(tampered, tenant_id="t1")


def test_local_kms_wrap_unwrap(monkeypatch) -> None:
    _set_crypto_env(monkeypatch)
    provider = LocalKmsProvider()
    key_ref = provider.build_key_ref(tenant_id="t1", key_alias="tenant-master", key_version=1)
    dek = b"\x01" * 32
    wrapped = provider.wrap_key(tenant_id="t1", dek=dek, key_ref=key_ref)
    unwrapped = provider.unwrap_key(tenant_id="t1", wrapped_dek=wrapped, key_ref=key_ref)
    assert unwrapped == dek


@pytest.mark.asyncio
async def test_key_rotation_state_transitions(monkeypatch) -> None:
    _set_crypto_env(monkeypatch)
    tenant_id = "t-crypto-rotate"
    async with SessionLocal() as session:
        active = await get_active_key(session, tenant_id)
        assert active.status == "active"
        new_key = await rotate_key(
            session,
            tenant_id=tenant_id,
            actor_id="ak1",
            actor_role="admin",
            reason="rotate",
        )
        old = await session.get(TenantKey, active.id)
        assert old is not None
        assert old.status == "retiring"
        assert new_key.key_version == active.key_version + 1


@pytest.mark.asyncio
async def test_rotation_job_reencrypts_blobs(monkeypatch) -> None:
    _set_crypto_env(monkeypatch)
    tenant_id = "t-crypto-job"
    async with SessionLocal() as session:
        active = await get_active_key(session, tenant_id)
        blob = await store_encrypted_blob(
            session,
            tenant_id=tenant_id,
            resource_type="dsar_artifact",
            resource_id="r3",
            plaintext=b"secret",
        )
        assert isinstance(blob, EncryptedBlob)
        new_key = await rotate_key(
            session,
            tenant_id=tenant_id,
            actor_id="ak1",
            actor_role="admin",
            reason="rotate",
        )
        job = await create_rotation_job(
            session,
            tenant_id=tenant_id,
            from_key_id=active.id,
            to_key_id=new_key.id,
        )
        job = await run_rotation_job(session, job=job, batch_size=1)
        refreshed = await session.get(EncryptedBlob, blob.id)
        assert refreshed is not None
        assert refreshed.key_id == new_key.id
        assert job.status == "completed"
