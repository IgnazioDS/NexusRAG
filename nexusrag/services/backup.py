from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Iterable, Literal, Protocol
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    ApiKey,
    BackupJob,
    Plan,
    PlanFeature,
    PlanLimit,
    RestoreDrill,
    TenantFeatureOverride,
    TenantPlanAssignment,
    UsageCounter,
    User,
)
from nexusrag.services.audit import record_event, record_system_event
from nexusrag.services.rollouts import get_rollout_state


BackupType = Literal["full", "schema", "metadata", "all"]
BackupComponent = Literal["db_full", "db_schema", "metadata"]
DumpRunner = Callable[[BackupComponent, Path, str], None]


@dataclass(frozen=True)
class BackupArtifact:
    # Describe a stored artifact so restore tooling can verify integrity.
    name: str
    path: str
    sha256: str
    size_bytes: int
    encrypted: bool


@dataclass(frozen=True)
class BackupManifest:
    # Keep backup manifests stable and explicit for restore tooling.
    backup_id: str
    created_at: str
    backup_type: str
    app_version: str
    manifest_version: str
    encryption_enabled: bool
    signing_enabled: bool
    components: list[BackupArtifact]

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "backup_type": self.backup_type,
            "app_version": self.app_version,
            "manifest_version": self.manifest_version,
            "encryption_enabled": self.encryption_enabled,
            "signing_enabled": self.signing_enabled,
            "components": [artifact.__dict__ for artifact in self.components],
        }


@dataclass(frozen=True)
class RestoreReport:
    # Summarize restore/validation outcomes for DR evidence.
    status: str
    manifest_uri: str
    started_at: str
    completed_at: str
    errors: list[str]
    rto_seconds: int | None


MANIFEST_VERSION = "1.0"
SIGNATURE_FILENAME = "signature.sig"


class BackupStorageAdapter(Protocol):
    # Allow custom storage backends (local/object storage) for backup artifacts.
    def job_dir(self, job_id: int) -> Path:
        ...

    def manifest_uri(self, manifest_path: Path) -> str:
        ...


@dataclass(frozen=True)
class LocalBackupStorage:
    # Default local filesystem storage adapter for backup artifacts.
    base_dir: Path

    def job_dir(self, job_id: int) -> Path:
        job_dir = self.base_dir / f"backup_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def manifest_uri(self, manifest_path: Path) -> str:
        return str(manifest_path)


def _utc_now() -> datetime:
    # Use UTC timestamps for DR artifacts and status reporting.
    return datetime.now(timezone.utc)


def _load_app_version() -> str:
    # Resolve the running package version for manifests.
    try:
        from importlib.metadata import version

        return version("nexusrag")
    except Exception:
        return "unknown"


def _decode_key(raw: str) -> bytes:
    # Accept hex or base64 encoded keys to align with operator tooling.
    cleaned = raw.strip()
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return base64.b64decode(cleaned)


def _encryption_key() -> bytes:
    # Enforce configured encryption keys when encryption is enabled.
    settings = get_settings()
    if not settings.backup_encryption_key:
        raise ValueError("BACKUP_ENCRYPTION_KEY is required when encryption is enabled")
    key = _decode_key(settings.backup_encryption_key)
    if len(key) not in {16, 24, 32}:
        raise ValueError("BACKUP_ENCRYPTION_KEY must be 128/192/256-bit")
    return key


def _signing_key() -> bytes:
    # Enforce configured signing keys when signing is enabled.
    settings = get_settings()
    if not settings.backup_signing_key:
        raise ValueError("BACKUP_SIGNING_KEY is required when signing is enabled")
    return settings.backup_signing_key.encode("utf-8")


def _sha256_file(path: Path) -> str:
    # Compute streaming checksums for large backup artifacts.
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _encrypt_file(source: Path, destination: Path, key: bytes) -> None:
    # Encrypt backup artifacts with AES-GCM to protect sensitive data at rest.
    nonce = os.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    encryptor = cipher.encryptor()
    with source.open("rb") as input_handle, destination.open("wb") as output_handle:
        output_handle.write(nonce)
        for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
            output_handle.write(encryptor.update(chunk))
        output_handle.write(encryptor.finalize())
        output_handle.write(encryptor.tag)


def _decrypt_file(source: Path, destination: Path, key: bytes) -> None:
    # Decrypt backup artifacts for restore operations.
    total_size = source.stat().st_size
    if total_size < 28:
        raise ValueError("Encrypted artifact is too small to contain nonce + tag")
    with source.open("rb") as input_handle:
        nonce = input_handle.read(12)
        input_handle.seek(total_size - 16)
        tag = input_handle.read(16)
        input_handle.seek(12)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
        decryptor = cipher.decryptor()
        remaining = total_size - 28
        with destination.open("wb") as output_handle:
            while remaining > 0:
                chunk = input_handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                output_handle.write(decryptor.update(chunk))
            output_handle.write(decryptor.finalize())


def _default_dump_runner(component: BackupComponent, output_path: Path, db_url: str) -> None:
    # Use pg_dump to produce logical backup artifacts without direct DB access.
    parsed = make_url(db_url)
    if "+asyncpg" in parsed.drivername:
        parsed = parsed.set(drivername=parsed.drivername.replace("+asyncpg", ""))
    pg_url = parsed.render_as_string(hide_password=False)
    args = ["pg_dump", "--no-owner", "--no-privileges", pg_url]
    if component == "db_schema":
        args.insert(1, "--schema-only")
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        if proc.stdout is None:
            raise RuntimeError("pg_dump produced no stdout stream")
        with gzip.open(output_path, "wb") as gzip_handle:
            shutil.copyfileobj(proc.stdout, gzip_handle)
        stderr = proc.stderr.read() if proc.stderr else b""
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {stderr.decode('utf-8', errors='ignore')}")


def get_dump_runner() -> DumpRunner:
    # Allow tests to monkeypatch dump behavior without touching API code.
    return _default_dump_runner


def _manifest_bytes(manifest: BackupManifest) -> bytes:
    # Serialize manifests deterministically for signing.
    return json.dumps(manifest.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign_manifest(manifest: BackupManifest, signing_key: bytes) -> str:
    # Produce HMAC SHA256 signatures for backup manifests.
    return hmac.new(signing_key, _manifest_bytes(manifest), hashlib.sha256).hexdigest()


def verify_signature(manifest: BackupManifest, signature: str, signing_key: bytes) -> bool:
    # Validate manifest signatures using constant-time comparison.
    expected = sign_manifest(manifest, signing_key)
    return hmac.compare_digest(expected, signature)


def _write_json_gzip(path: Path, payload: dict[str, Any]) -> None:
    # Store metadata snapshots compressed to reduce storage cost.
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), ensure_ascii=False)


async def collect_metadata_snapshot(session: AsyncSession) -> dict[str, Any]:
    # Capture metadata required for DR restore verification without secrets.
    plans = (await session.execute(select(Plan).order_by(Plan.id))).scalars().all()
    plan_features = (
        await session.execute(select(PlanFeature).order_by(PlanFeature.plan_id, PlanFeature.feature_key))
    ).scalars().all()
    assignments = (
        await session.execute(
            select(TenantPlanAssignment).order_by(
                TenantPlanAssignment.tenant_id, TenantPlanAssignment.effective_from
            )
        )
    ).scalars().all()
    overrides = (
        await session.execute(
            select(TenantFeatureOverride).order_by(
                TenantFeatureOverride.tenant_id, TenantFeatureOverride.feature_key
            )
        )
    ).scalars().all()
    plan_limits = (await session.execute(select(PlanLimit).order_by(PlanLimit.tenant_id))).scalars().all()
    usage_counters = (
        await session.execute(select(UsageCounter).order_by(UsageCounter.tenant_id, UsageCounter.period_start))
    ).scalars().all()
    api_key_rows = (
        await session.execute(select(ApiKey, User.role).join(User, ApiKey.user_id == User.id))
    ).all()
    rollout_state = await get_rollout_state()

    api_keys = []
    for api_key, role in api_key_rows:
        api_keys.append(
            {
                "id": api_key.id,
                "tenant_id": api_key.tenant_id,
                "user_id": api_key.user_id,
                "role": role,
                "key_prefix": api_key.key_prefix,
                "name": api_key.name,
                "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
                "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
                "revoked_at": api_key.revoked_at.isoformat() if api_key.revoked_at else None,
            }
        )

    return {
        "captured_at": _utc_now().isoformat(),
        "plans": [
            {"id": plan.id, "name": plan.name, "is_active": plan.is_active} for plan in plans
        ],
        "plan_features": [
            {
                "plan_id": feature.plan_id,
                "feature_key": feature.feature_key,
                "enabled": feature.enabled,
                "config_json": feature.config_json,
            }
            for feature in plan_features
        ],
        "plan_assignments": [
            {
                "tenant_id": assignment.tenant_id,
                "plan_id": assignment.plan_id,
                "effective_from": assignment.effective_from.isoformat(),
                "effective_to": assignment.effective_to.isoformat() if assignment.effective_to else None,
                "is_active": assignment.is_active,
            }
            for assignment in assignments
        ],
        "feature_overrides": [
            {
                "tenant_id": override.tenant_id,
                "feature_key": override.feature_key,
                "enabled": override.enabled,
                "config_json": override.config_json,
            }
            for override in overrides
        ],
        "plan_limits": [
            {
                "tenant_id": limit.tenant_id,
                "daily_requests_limit": limit.daily_requests_limit,
                "monthly_requests_limit": limit.monthly_requests_limit,
                "daily_tokens_limit": limit.daily_tokens_limit,
                "monthly_tokens_limit": limit.monthly_tokens_limit,
                "soft_cap_ratio": limit.soft_cap_ratio,
                "hard_cap_enabled": limit.hard_cap_enabled,
            }
            for limit in plan_limits
        ],
        "usage_counters": [
            {
                "tenant_id": counter.tenant_id,
                "period_type": counter.period_type,
                "period_start": counter.period_start.isoformat(),
                "requests_count": counter.requests_count,
                "estimated_tokens_count": counter.estimated_tokens_count,
                "updated_at": counter.updated_at.isoformat() if counter.updated_at else None,
            }
            for counter in usage_counters
        ],
        "api_keys": api_keys,
        "rollouts": {
            "kill_switches": rollout_state.kill_switches,
            "canary_percentages": rollout_state.canary_percentages,
        },
    }


def _write_manifest(path: Path, manifest: BackupManifest) -> None:
    # Persist the manifest alongside artifacts for restore validation.
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)
    path.write_text(payload, encoding="utf-8")


def _load_manifest(path: Path) -> BackupManifest:
    # Parse manifests into typed structures for validation.
    payload = json.loads(path.read_text(encoding="utf-8"))
    components = [
        BackupArtifact(
            name=item["name"],
            path=item["path"],
            sha256=item["sha256"],
            size_bytes=int(item["size_bytes"]),
            encrypted=bool(item.get("encrypted", False)),
        )
        for item in payload.get("components", [])
    ]
    return BackupManifest(
        backup_id=payload["backup_id"],
        created_at=payload["created_at"],
        backup_type=payload.get("backup_type", "unknown"),
        app_version=payload.get("app_version", "unknown"),
        manifest_version=payload.get("manifest_version", MANIFEST_VERSION),
        encryption_enabled=bool(payload.get("encryption_enabled", False)),
        signing_enabled=bool(payload.get("signing_enabled", False)),
        components=components,
    )


async def create_backup_job(
    session: AsyncSession,
    *,
    backup_type: str,
    created_by_actor_id: str | None,
    tenant_scope: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BackupJob:
    # Create a backup job row so ops endpoints can track execution.
    job = BackupJob(
        tenant_scope=tenant_scope,
        backup_type=backup_type,
        status="queued",
        manifest_uri=None,
        started_at=_utc_now(),
        completed_at=None,
        error_code=None,
        error_message=None,
        created_by_actor_id=created_by_actor_id,
        metadata_json=metadata or {},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def update_backup_job(
    session: AsyncSession,
    job: BackupJob,
    *,
    status: str,
    manifest_uri: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    # Persist backup job status for readiness checks.
    job.status = status
    if manifest_uri is not None:
        job.manifest_uri = manifest_uri
    job.error_code = error_code
    job.error_message = error_message
    if status in {"succeeded", "failed"}:
        job.completed_at = _utc_now()
    await session.commit()


async def create_restore_drill(
    session: AsyncSession,
    *,
    status: str,
    report_json: dict[str, Any] | None = None,
    rto_seconds: int | None = None,
    verified_manifest_uri: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> RestoreDrill:
    # Create a restore drill record for compliance evidence.
    drill = RestoreDrill(
        status=status,
        started_at=_utc_now(),
        completed_at=_utc_now() if status in {"passed", "failed"} else None,
        report_json=report_json,
        rto_seconds=rto_seconds,
        verified_manifest_uri=verified_manifest_uri,
        error_code=error_code,
        error_message=error_message,
    )
    session.add(drill)
    await session.commit()
    await session.refresh(drill)
    return drill


async def update_restore_drill(
    session: AsyncSession,
    drill: RestoreDrill,
    *,
    status: str,
    report_json: dict[str, Any] | None = None,
    rto_seconds: int | None = None,
    verified_manifest_uri: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    # Persist restore drill completion details for readiness checks.
    drill.status = status
    drill.report_json = report_json
    drill.rto_seconds = rto_seconds
    drill.verified_manifest_uri = verified_manifest_uri
    drill.error_code = error_code
    drill.error_message = error_message
    if status in {"passed", "failed"}:
        drill.completed_at = _utc_now()
    await session.commit()


async def create_backup_artifacts(
    *,
    session: AsyncSession,
    job_id: int,
    backup_type: BackupType,
    output_dir: Path,
    dump_runner: DumpRunner | None = None,
    storage: BackupStorageAdapter | None = None,
) -> tuple[BackupManifest, Path, str]:
    # Generate backup artifacts and manifest under the specified output directory.
    settings = get_settings()
    output_dir.mkdir(parents=True, exist_ok=True)
    storage = storage or LocalBackupStorage(output_dir)
    job_dir = storage.job_dir(job_id)

    encryption_enabled = bool(settings.backup_encryption_enabled)
    signing_enabled = bool(settings.backup_signing_enabled)
    encryption_key = _encryption_key() if encryption_enabled else b""
    dump_runner = dump_runner or get_dump_runner()
    components: list[BackupArtifact] = []

    def _finalize_artifact(component: BackupComponent, source_path: Path) -> None:
        # Encrypt and hash the artifact before recording it in the manifest.
        target_path = source_path
        encrypted = False
        if encryption_enabled:
            encrypted = True
            target_path = source_path.with_suffix(source_path.suffix + ".enc")
            _encrypt_file(source_path, target_path, encryption_key)
            source_path.unlink(missing_ok=True)
        checksum = _sha256_file(target_path)
        size_bytes = target_path.stat().st_size
        components.append(
            BackupArtifact(
                name=component,
                path=target_path.name,
                sha256=checksum,
                size_bytes=size_bytes,
                encrypted=encrypted,
            )
        )

    if backup_type in {"full", "all"}:
        full_path = job_dir / "db_full.sql.gz"
        dump_runner("db_full", full_path, settings.database_url)
        _finalize_artifact("db_full", full_path)

    if backup_type in {"schema", "all"}:
        schema_path = job_dir / "db_schema.sql.gz"
        dump_runner("db_schema", schema_path, settings.database_url)
        _finalize_artifact("db_schema", schema_path)

    if backup_type in {"metadata", "all"}:
        metadata_path = job_dir / "metadata_snapshot.json.gz"
        snapshot = await collect_metadata_snapshot(session)
        _write_json_gzip(metadata_path, snapshot)
        _finalize_artifact("metadata", metadata_path)

    manifest = BackupManifest(
        backup_id=str(job_id),
        created_at=_utc_now().isoformat(),
        backup_type=backup_type,
        app_version=_load_app_version(),
        manifest_version=MANIFEST_VERSION,
        encryption_enabled=encryption_enabled,
        signing_enabled=signing_enabled,
        components=components,
    )
    manifest_path = job_dir / "manifest.json"
    _write_manifest(manifest_path, manifest)

    if signing_enabled:
        signature = sign_manifest(manifest, _signing_key())
        (job_dir / SIGNATURE_FILENAME).write_text(signature, encoding="utf-8")

    if settings.backup_verify_on_create:
        errors = validate_manifest(manifest_path, require_signature=signing_enabled)
        if errors:
            raise RuntimeError(f"backup verification failed: {', '.join(errors)}")

    return manifest, manifest_path, storage.manifest_uri(manifest_path)


def validate_manifest(
    manifest_path: Path,
    *,
    require_signature: bool,
) -> list[str]:
    # Validate manifest schema, signature, and artifact checksums.
    errors: list[str] = []
    manifest = _load_manifest(manifest_path)
    job_dir = manifest_path.parent
    if manifest.manifest_version != MANIFEST_VERSION:
        errors.append("manifest version mismatch")

    if require_signature:
        signature_path = job_dir / SIGNATURE_FILENAME
        if not signature_path.exists():
            errors.append("signature file missing")
        else:
            signature = signature_path.read_text(encoding="utf-8").strip()
            try:
                key = _signing_key()
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if not verify_signature(manifest, signature, key):
                    errors.append("manifest signature invalid")

    for component in manifest.components:
        artifact_path = job_dir / component.path
        if not artifact_path.exists():
            errors.append(f"missing artifact: {component.path}")
            continue
        checksum = _sha256_file(artifact_path)
        if checksum != component.sha256:
            errors.append(f"checksum mismatch for {component.path}")

    return errors


def restore_from_manifest(
    *,
    manifest_path: Path,
    components: Iterable[str],
    target_db_url: str,
    dry_run: bool,
    allow_destructive: bool,
) -> RestoreReport:
    # Restore selected components from a backup manifest with validation.
    start = time.monotonic()
    started_at = _utc_now().isoformat()
    errors = validate_manifest(manifest_path, require_signature=get_settings().restore_require_signature)
    if errors:
        completed_at = _utc_now().isoformat()
        return RestoreReport(
            status="failed",
            manifest_uri=str(manifest_path),
            started_at=started_at,
            completed_at=completed_at,
            errors=errors,
            rto_seconds=int(time.monotonic() - start),
        )

    manifest = _load_manifest(manifest_path)
    selected = set(components)
    if "all" in selected:
        selected = {"db", "schema", "metadata"}

    if not dry_run and ({"db", "schema"} & selected) and not allow_destructive:
        completed_at = _utc_now().isoformat()
        return RestoreReport(
            status="failed",
            manifest_uri=str(manifest_path),
            started_at=started_at,
            completed_at=completed_at,
            errors=["destructive restore requires explicit confirmation"],
            rto_seconds=int(time.monotonic() - start),
        )

    if dry_run:
        completed_at = _utc_now().isoformat()
        return RestoreReport(
            status="passed",
            manifest_uri=str(manifest_path),
            started_at=started_at,
            completed_at=completed_at,
            errors=[],
            rto_seconds=int(time.monotonic() - start),
        )

    job_dir = manifest_path.parent
    encryption_enabled = manifest.encryption_enabled
    key = _encryption_key() if encryption_enabled else b""

    def _materialize_artifact(name: str) -> Path:
        artifact = next((item for item in manifest.components if item.name == name), None)
        if artifact is None:
            raise FileNotFoundError(f"{name} artifact not found in manifest")
        source = job_dir / artifact.path
        if not encryption_enabled:
            return source
        destination = job_dir / f"restore_{uuid4().hex}_{name}"
        _decrypt_file(source, destination, key)
        return destination

    if "db" in selected:
        full_path = _materialize_artifact("db_full")
        _restore_sql_dump(full_path, target_db_url)
    if "schema" in selected:
        schema_path = _materialize_artifact("db_schema")
        _restore_sql_dump(schema_path, target_db_url)
    # Metadata restore is a no-op for now; operators can re-apply via admin tooling.

    completed_at = _utc_now().isoformat()
    return RestoreReport(
        status="passed",
        manifest_uri=str(manifest_path),
        started_at=started_at,
        completed_at=completed_at,
        errors=[],
        rto_seconds=int(time.monotonic() - start),
    )


def _restore_sql_dump(path: Path, db_url: str) -> None:
    # Apply SQL dumps via psql to the target database.
    parsed = make_url(db_url)
    if "+asyncpg" in parsed.drivername:
        parsed = parsed.set(drivername=parsed.drivername.replace("+asyncpg", ""))
    pg_url = parsed.render_as_string(hide_password=False)
    with gzip.open(path, "rb") as handle:
        process = subprocess.Popen(
            ["psql", pg_url],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate(handle.read())
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="ignore"))


async def emit_backup_event(
    *,
    event_type: str,
    outcome: str,
    actor_type: str,
    tenant_id: str | None,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    # Keep DR audit events consistent and sanitized.
    await record_event(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_role=actor_role,
        event_type=event_type,
        outcome=outcome,
        resource_type="dr",
        resource_id=event_type,
        request_id=request_id,
        ip_address=None,
        user_agent=None,
        metadata=metadata,
        error_code=error_code,
        commit=True,
        best_effort=True,
    )


async def run_backup_job(
    *,
    session: AsyncSession,
    job: BackupJob,
    backup_type: BackupType,
    output_dir: Path,
    actor_type: str,
    tenant_id: str | None,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> None:
    # Execute a backup job and persist status updates with audit events.
    await emit_backup_event(
        event_type="dr.backup.started",
        outcome="success",
        actor_type=actor_type,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
        metadata={"backup_type": backup_type, "job_id": job.id},
    )
    job.status = "running"
    await session.commit()
    try:
        manifest, manifest_path, manifest_uri = await create_backup_artifacts(
            session=session,
            job_id=job.id,
            backup_type=backup_type,
            output_dir=output_dir,
        )
        await update_backup_job(
            session,
            job,
            status="succeeded",
            manifest_uri=manifest_uri,
        )
        await emit_backup_event(
            event_type="dr.backup.succeeded",
            outcome="success",
            actor_type=actor_type,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            metadata={"backup_id": manifest.backup_id, "manifest_uri": manifest_uri},
        )
    except Exception as exc:  # noqa: BLE001 - DR failures are surfaced via status/errors
        await update_backup_job(
            session,
            job,
            status="failed",
            error_code="BACKUP_FAILED",
            error_message=str(exc),
        )
        await emit_backup_event(
            event_type="dr.backup.failed",
            outcome="failure",
            actor_type=actor_type,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            metadata={"backup_type": backup_type},
            error_code="BACKUP_FAILED",
        )
        raise


async def run_restore_drill(
    *,
    session: AsyncSession,
    manifest_uri: str,
    actor_type: str,
    tenant_id: str | None,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
    drill_id: int | None = None,
) -> RestoreDrill:
    # Execute a restore drill (dry-run validation) and persist the report.
    await emit_backup_event(
        event_type="dr.restore_drill.started",
        outcome="success",
        actor_type=actor_type,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
        metadata={"manifest_uri": manifest_uri},
    )
    manifest_path = Path(manifest_uri)
    report = restore_from_manifest(
        manifest_path=manifest_path,
        components=["all"],
        target_db_url=get_settings().database_url,
        dry_run=True,
        allow_destructive=False,
    )
    status = "passed" if report.status == "passed" else "failed"
    report_payload = {
        "manifest_uri": report.manifest_uri,
        "errors": report.errors,
        "started_at": report.started_at,
        "completed_at": report.completed_at,
    }
    if drill_id is None:
        drill = await create_restore_drill(
            session,
            status=status,
            report_json=report_payload,
            rto_seconds=report.rto_seconds,
            verified_manifest_uri=manifest_uri,
            error_code="RESTORE_VALIDATION_FAILED" if status == "failed" else None,
            error_message="; ".join(report.errors) if report.errors else None,
        )
    else:
        drill = await session.get(RestoreDrill, drill_id)
        if drill is None:
            drill = await create_restore_drill(
                session,
                status=status,
                report_json=report_payload,
                rto_seconds=report.rto_seconds,
                verified_manifest_uri=manifest_uri,
                error_code="RESTORE_VALIDATION_FAILED" if status == "failed" else None,
                error_message="; ".join(report.errors) if report.errors else None,
            )
        else:
            await update_restore_drill(
                session,
                drill,
                status=status,
                report_json=report_payload,
                rto_seconds=report.rto_seconds,
                verified_manifest_uri=manifest_uri,
                error_code="RESTORE_VALIDATION_FAILED" if status == "failed" else None,
                error_message="; ".join(report.errors) if report.errors else None,
            )
    await emit_backup_event(
        event_type=f"dr.restore_drill.{status}",
        outcome="success" if status == "passed" else "failure",
        actor_type=actor_type,
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        request_id=request_id,
        metadata={"manifest_uri": manifest_uri},
        error_code="RESTORE_VALIDATION_FAILED" if status == "failed" else None,
    )
    return drill


async def prune_backups(
    *,
    session: AsyncSession,
    base_dir: Path,
    retention_days: int,
    held_backup_scope_ids: set[str] | None = None,
) -> int:
    # Remove backup artifacts beyond retention and mark jobs as pruned.
    cutoff = _utc_now() - timedelta(days=retention_days)
    pruned = 0
    skipped_hold = 0
    updated = False
    hold_scope_ids = held_backup_scope_ids or set()
    if not base_dir.exists():
        return 0
    for manifest_path in base_dir.rglob("manifest.json"):
        manifest = _load_manifest(manifest_path)
        created_at = datetime.fromisoformat(manifest.created_at)
        if created_at >= cutoff:
            continue
        manifest_uri = str(manifest_path)
        if manifest.backup_id in hold_scope_ids or manifest_uri in hold_scope_ids:
            skipped_hold += 1
            continue
        job_dir = manifest_path.parent
        shutil.rmtree(job_dir, ignore_errors=True)
        pruned += 1
        try:
            job_id = int(manifest.backup_id)
        except ValueError:
            job_id = None
        if job_id is not None:
            job = await session.get(BackupJob, job_id)
            if job is not None:
                job.status = "pruned"
                job.completed_at = _utc_now()
                updated = True
    if updated:
        await session.commit()
    if pruned:
        await record_system_event(
            event_type="dr.backup.pruned",
            metadata={"count": pruned},
        )
    if skipped_hold:
        await record_system_event(
            event_type="governance.retention.item.skipped_hold",
            metadata={"category": "backups", "skipped_count": skipped_hold},
        )
    return pruned
