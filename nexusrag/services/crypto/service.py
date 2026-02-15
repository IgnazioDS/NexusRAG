from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import EncryptedBlob, KeyRotationJob, TenantKey
from nexusrag.services.audit import record_event
from nexusrag.services.crypto.envelope import EnvelopeResult, decrypt_payload, encrypt_payload
from nexusrag.services.crypto.kms import get_kms_provider
from nexusrag.services.crypto.utils import b64decode_str, b64encode_bytes
from nexusrag.services.telemetry import increment_counter, set_gauge


logger = logging.getLogger(__name__)

CRYPTO_RESOURCE_AUDIO = "audio_blob"
CRYPTO_RESOURCE_DSAR = "dsar_artifact"
CRYPTO_RESOURCE_BACKUP_MANIFEST = "backup_manifest"
CRYPTO_RESOURCE_BACKUP_METADATA = "backup_metadata"


class CryptoUnavailableError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _crypto_error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _check_crypto_available() -> None:
    settings = get_settings()
    if not settings.crypto_enabled:
        raise CryptoUnavailableError("Encryption is disabled")
    try:
        get_kms_provider()
    except Exception as exc:
        logger.warning("crypto_provider_unavailable", exc_info=exc)
        raise CryptoUnavailableError("KMS provider unavailable") from exc


def ensure_encryption_available() -> None:
    # Expose crypto availability checks for policy enforcement.
    settings = get_settings()
    try:
        _check_crypto_available()
    except CryptoUnavailableError as exc:
        if settings.crypto_fail_mode == "open":
            increment_counter("crypto_fail_open_total")
            return
        code = "KMS_UNAVAILABLE" if "KMS" in str(exc) else "ENCRYPTION_REQUIRED"
        raise _crypto_error(code, str(exc), 503) from exc


def _extract_cipher_bytes(blob: EncryptedBlob) -> bytes:
    # Allow cipher_text to be stored inline or as a file:// URI for large payloads.
    cipher_text = blob.cipher_text
    if cipher_text.startswith("file://"):
        path = Path(cipher_text.removeprefix("file://"))
        return path.read_bytes()
    return b64decode_str(cipher_text)


def _write_cipher_bytes(target: Path, payload: bytes) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return f"file://{target}"


def _build_envelope_from_blob(blob: EncryptedBlob, *, key_ref: str, key_version: int, provider: str) -> EnvelopeResult:
    return EnvelopeResult(
        wrapped_dek=blob.wrapped_dek,
        key_ref=key_ref,
        key_version=key_version,
        provider=provider,
        nonce=blob.nonce,
        tag=blob.tag,
        cipher_text=blob.cipher_text,
        aad_json=blob.aad_json,
        checksum_sha256=blob.checksum_sha256,
    )


def _choose_storage_path(resource_type: str, resource_id: str) -> Path | None:
    settings = get_settings()
    if resource_type != CRYPTO_RESOURCE_AUDIO:
        return None
    # Keep audio ciphertext on disk to avoid large DB rows.
    audio_dir = Path("var") / "audio"
    return audio_dir / f"{resource_id}.enc"


def _key_status_active() -> str:
    return "active"


def _key_status_retiring() -> str:
    return "retiring"


def _key_status_retired() -> str:
    return "retired"


def _rotation_status_active() -> set[str]:
    return {"queued", "running", "paused"}




async def get_active_key(session: AsyncSession, tenant_id: str) -> TenantKey:
    settings = get_settings()
    query = (
        select(TenantKey)
        .where(TenantKey.tenant_id == tenant_id, TenantKey.status == _key_status_active())
        .order_by(TenantKey.key_version.desc())
        .limit(1)
    )
    active = (await session.execute(query)).scalar_one_or_none()
    if active is not None:
        return active

    kms = get_kms_provider()
    key_alias = settings.crypto_default_key_alias
    key_version = 1
    key_ref = kms.build_key_ref(tenant_id=tenant_id, key_alias=key_alias, key_version=key_version)
    new_key = TenantKey(
        tenant_id=tenant_id,
        key_alias=key_alias,
        key_version=key_version,
        provider=settings.crypto_provider,
        key_ref=key_ref,
        status=_key_status_active(),
        activated_at=_utc_now(),
    )
    session.add(new_key)
    await session.commit()
    await session.refresh(new_key)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="crypto.key.created",
        outcome="success",
        resource_type="tenant_key",
        resource_id=str(new_key.id),
        metadata={"key_alias": key_alias, "key_version": key_version},
        commit=True,
        best_effort=True,
    )
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="system",
        actor_id=None,
        actor_role=None,
        event_type="crypto.key.activated",
        outcome="success",
        resource_type="tenant_key",
        resource_id=str(new_key.id),
        metadata={"key_alias": key_alias, "key_version": key_version},
        commit=True,
        best_effort=True,
    )
    return new_key


async def rotate_key(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str | None,
    actor_role: str | None,
    reason: str | None,
) -> TenantKey:
    try:
        _check_crypto_available()
    except CryptoUnavailableError as exc:
        raise _crypto_error("KMS_UNAVAILABLE", str(exc), 503) from exc
    settings = get_settings()
    try:
        active = await get_active_key(session, tenant_id)
    except Exception as exc:  # noqa: BLE001
        raise _crypto_error("KMS_UNAVAILABLE", "KMS provider unavailable", 503) from exc
    next_version = active.key_version + 1
    kms = get_kms_provider()
    key_ref = kms.build_key_ref(
        tenant_id=tenant_id,
        key_alias=settings.crypto_default_key_alias,
        key_version=next_version,
    )
    active.status = _key_status_retiring()
    new_key = TenantKey(
        tenant_id=tenant_id,
        key_alias=settings.crypto_default_key_alias,
        key_version=next_version,
        provider=settings.crypto_provider,
        key_ref=key_ref,
        status=_key_status_active(),
        activated_at=_utc_now(),
    )
    session.add(new_key)
    await session.commit()
    await session.refresh(new_key)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="crypto.key.created",
        outcome="success",
        resource_type="tenant_key",
        resource_id=str(new_key.id),
        metadata={"key_version": next_version, "reason": reason},
        commit=True,
        best_effort=True,
    )
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="crypto.key.activated",
        outcome="success",
        resource_type="tenant_key",
        resource_id=str(new_key.id),
        metadata={"from_key_id": active.id, "reason": reason, "key_version": next_version},
        commit=True,
        best_effort=True,
    )
    return new_key


async def store_encrypted_blob(
    session: AsyncSession,
    *,
    tenant_id: str,
    resource_type: str,
    resource_id: str,
    plaintext: bytes,
    created_at: datetime | None = None,
) -> EncryptedBlob | None:
    settings = get_settings()
    try:
        _check_crypto_available()
    except CryptoUnavailableError as exc:
        if not settings.crypto_require_encryption_for_sensitive or settings.crypto_fail_mode == "open":
            increment_counter("unencrypted_sensitive_items_total")
            return None
        code = "KMS_UNAVAILABLE" if "KMS" in str(exc) else "ENCRYPTION_REQUIRED"
        raise _crypto_error(code, str(exc), 503) from exc
    created_at = created_at or _utc_now()
    try:
        active_key = await get_active_key(session, tenant_id)
    except Exception as exc:  # noqa: BLE001
        if not settings.crypto_require_encryption_for_sensitive or settings.crypto_fail_mode == "open":
            increment_counter("unencrypted_sensitive_items_total")
            return None
        raise _crypto_error("KMS_UNAVAILABLE", "KMS provider unavailable", 503) from exc
    try:
        envelope = encrypt_payload(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            plaintext=plaintext,
            key_ref=active_key.key_ref,
            key_version=active_key.key_version,
            provider=active_key.provider,
            created_at=created_at,
        )
    except Exception as exc:  # noqa: BLE001
        increment_counter("crypto_failures_total")
        if not settings.crypto_require_encryption_for_sensitive or settings.crypto_fail_mode == "open":
            increment_counter("unencrypted_sensitive_items_total")
            return None
        raise _crypto_error("KMS_UNAVAILABLE", "KMS provider unavailable", 503) from exc
    cipher_bytes = b64decode_str(envelope.cipher_text)
    storage_path = _choose_storage_path(resource_type, resource_id)
    cipher_text_value = envelope.cipher_text
    if storage_path is not None:
        cipher_text_value = _write_cipher_bytes(storage_path, cipher_bytes)
    blob = EncryptedBlob(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        key_id=active_key.id,
        wrapped_dek=envelope.wrapped_dek,
        nonce=envelope.nonce,
        tag=envelope.tag,
        cipher_text=cipher_text_value,
        aad_json=envelope.aad_json,
        checksum_sha256=envelope.checksum_sha256,
    )
    session.add(blob)
    await session.commit()
    await session.refresh(blob)
    increment_counter("crypto_encrypt_ops_total")
    total = await session.scalar(select(func.count()).select_from(EncryptedBlob))
    set_gauge("encrypted_sensitive_items_total", float(total or 0))
    return blob


async def decrypt_blob(session: AsyncSession, *, blob: EncryptedBlob) -> bytes:
    _check_crypto_available()
    key = await session.get(TenantKey, blob.key_id)
    if key is None or key.status not in {_key_status_active(), _key_status_retiring(), _key_status_retired()}:
        raise _crypto_error("KEY_NOT_ACTIVE", "Encryption key is not available", 409)
    envelope = _build_envelope_from_blob(blob, key_ref=key.key_ref, key_version=key.key_version, provider=key.provider)
    # Replace cipher_text with inline base64 if stored on disk.
    cipher_bytes = _extract_cipher_bytes(blob)
    envelope = EnvelopeResult(
        wrapped_dek=envelope.wrapped_dek,
        key_ref=envelope.key_ref,
        key_version=envelope.key_version,
        provider=envelope.provider,
        nonce=envelope.nonce,
        tag=envelope.tag,
        cipher_text=b64encode_bytes(cipher_bytes),
        aad_json=envelope.aad_json,
        checksum_sha256=envelope.checksum_sha256,
    )
    try:
        plaintext = decrypt_payload(envelope, tenant_id=blob.tenant_id)
    except Exception as exc:  # noqa: BLE001
        increment_counter("crypto_failures_total")
        raise _crypto_error("DECRYPTION_FAILED", "Unable to decrypt payload", 500) from exc
    increment_counter("crypto_decrypt_ops_total")
    return plaintext


async def get_encrypted_blob(
    session: AsyncSession,
    *,
    tenant_id: str,
    resource_type: str,
    resource_id: str,
) -> EncryptedBlob | None:
    query = (
        select(EncryptedBlob)
        .where(
            EncryptedBlob.tenant_id == tenant_id,
            EncryptedBlob.resource_type == resource_type,
            EncryptedBlob.resource_id == resource_id,
        )
        .order_by(EncryptedBlob.created_at.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalar_one_or_none()


async def create_rotation_job(
    session: AsyncSession,
    *,
    tenant_id: str,
    from_key_id: int,
    to_key_id: int,
) -> KeyRotationJob:
    active_job = (
        await session.execute(
            select(KeyRotationJob)
            .where(KeyRotationJob.tenant_id == tenant_id, KeyRotationJob.status.in_(_rotation_status_active()))
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_job is not None:
        raise _crypto_error("KEY_ROTATION_IN_PROGRESS", "Key rotation already in progress", 409)
    job = KeyRotationJob(
        tenant_id=tenant_id,
        from_key_id=from_key_id,
        to_key_id=to_key_id,
        status="queued",
        total_items=0,
        processed_items=0,
        failed_items=0,
        report_json={"failures": []},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    increment_counter("key_rotation_jobs_total")
    return job


async def run_rotation_job(
    session: AsyncSession,
    *,
    job: KeyRotationJob,
    batch_size: int | None = None,
) -> KeyRotationJob:
    settings = get_settings()
    batch_size = batch_size or settings.crypto_reencrypt_batch_size
    if job.status == "completed" or job.status == "failed":
        return job
    if job.status == "paused":
        return job
    job.status = "running"
    if job.started_at is None:
        job.started_at = _utc_now()
    await session.commit()

    total = await session.scalar(
        select(func.count()).where(EncryptedBlob.tenant_id == job.tenant_id, EncryptedBlob.key_id == job.from_key_id)
    )
    job.total_items = int(total or 0)
    await session.commit()

    while True:
        if job.status == "paused":
            break
        rows = (
            await session.execute(
                select(EncryptedBlob)
                .where(EncryptedBlob.tenant_id == job.tenant_id, EncryptedBlob.key_id == job.from_key_id)
                .order_by(EncryptedBlob.id.asc())
                .limit(batch_size)
            )
        ).scalars().all()
        if not rows:
            break
        for blob in rows:
            try:
                plaintext = await decrypt_blob(session, blob=blob)
                # Re-encrypt with the new key version.
                active_key = await session.get(TenantKey, job.to_key_id)
                if active_key is None:
                    raise _crypto_error("KEY_NOT_ACTIVE", "Rotation target key missing", 409)
                envelope = encrypt_payload(
                    tenant_id=blob.tenant_id,
                    resource_type=blob.resource_type,
                    resource_id=blob.resource_id,
                    plaintext=plaintext,
                    key_ref=active_key.key_ref,
                    key_version=active_key.key_version,
                    provider=active_key.provider,
                    created_at=_utc_now(),
                )
                cipher_bytes = b64decode_str(envelope.cipher_text)
                cipher_text_value = envelope.cipher_text
                if blob.cipher_text.startswith("file://"):
                    path = Path(blob.cipher_text.removeprefix("file://"))
                    cipher_text_value = _write_cipher_bytes(path, cipher_bytes)
                blob.key_id = active_key.id
                blob.wrapped_dek = envelope.wrapped_dek
                blob.nonce = envelope.nonce
                blob.tag = envelope.tag
                blob.cipher_text = cipher_text_value
                blob.aad_json = envelope.aad_json
                blob.checksum_sha256 = envelope.checksum_sha256
                job.processed_items += 1
            except HTTPException:
                job.failed_items += 1
                failures = job.report_json.get("failures") if isinstance(job.report_json, dict) else []
                if isinstance(failures, list):
                    failures.append({"blob_id": blob.id, "error": "rotation_failed"})
                    job.report_json["failures"] = failures
            except Exception:  # noqa: BLE001
                job.failed_items += 1
        await session.commit()
        if job.total_items:
            pct = (job.processed_items / max(job.total_items, 1)) * 100.0
            set_gauge(f"key_rotation_progress_percent.{job.id}", pct)
        await record_event(
            session=session,
            tenant_id=job.tenant_id,
            actor_type="system",
            actor_id=None,
            actor_role=None,
            event_type="crypto.rotation.progress",
            outcome="success",
            resource_type="key_rotation_job",
            resource_id=str(job.id),
            metadata={
                "processed_items": job.processed_items,
                "failed_items": job.failed_items,
                "total_items": job.total_items,
            },
            commit=True,
            best_effort=True,
        )

    if job.failed_items > 0 and job.processed_items < job.total_items:
        job.status = "failed"
        job.error_code = "KEY_ROTATION_FAILED"
        job.error_message = "One or more items failed to re-encrypt"
    else:
        job.status = "completed"
    job.completed_at = _utc_now()
    await session.commit()

    if job.status == "completed":
        from_key = await session.get(TenantKey, job.from_key_id)
        if from_key is not None:
            from_key.status = _key_status_retired()
            from_key.retired_at = _utc_now()
            await session.commit()
            await record_event(
                session=session,
                tenant_id=job.tenant_id,
                actor_type="system",
                actor_id=None,
                actor_role=None,
                event_type="crypto.key.retired",
                outcome="success",
                resource_type="tenant_key",
                resource_id=str(from_key.id),
                metadata={"key_version": from_key.key_version},
                commit=True,
                best_effort=True,
            )

    return job


async def pause_rotation_job(session: AsyncSession, *, job: KeyRotationJob) -> KeyRotationJob:
    if job.status in {"completed", "failed"}:
        return job
    job.status = "paused"
    await session.commit()
    return job


async def resume_rotation_job(session: AsyncSession, *, job: KeyRotationJob) -> KeyRotationJob:
    if job.status != "paused":
        return job
    job.status = "queued"
    await session.commit()
    return job


async def cancel_rotation_job(session: AsyncSession, *, job: KeyRotationJob) -> KeyRotationJob:
    if job.status in {"completed", "failed"}:
        return job
    job.status = "failed"
    job.error_code = "KEY_ROTATION_FAILED"
    job.error_message = "Rotation cancelled"
    job.completed_at = _utc_now()
    await session.commit()
    return job


def build_envelope_wrapper(envelope: EnvelopeResult) -> dict[str, Any]:
    # Provide a JSON wrapper for encrypted manifests without DB access.
    return {
        "encryption": "envelope",
        "wrapped_dek": envelope.wrapped_dek,
        "key_ref": envelope.key_ref,
        "key_version": envelope.key_version,
        "provider": envelope.provider,
        "nonce": envelope.nonce,
        "tag": envelope.tag,
        "cipher_text": envelope.cipher_text,
        "aad_json": envelope.aad_json,
        "checksum_sha256": envelope.checksum_sha256,
    }


def parse_envelope_wrapper(wrapper: dict[str, Any]) -> EnvelopeResult:
    return EnvelopeResult(
        wrapped_dek=str(wrapper.get("wrapped_dek")),
        key_ref=str(wrapper.get("key_ref")),
        key_version=int(wrapper.get("key_version")),
        provider=str(wrapper.get("provider")),
        nonce=str(wrapper.get("nonce")),
        tag=str(wrapper.get("tag")),
        cipher_text=str(wrapper.get("cipher_text")),
        aad_json=dict(wrapper.get("aad_json") or {}),
        checksum_sha256=str(wrapper.get("checksum_sha256")),
    )
