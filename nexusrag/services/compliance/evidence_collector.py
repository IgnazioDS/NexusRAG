from __future__ import annotations

import hashlib
import hmac
import json
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import AuditEvent, EvidenceBundle
from nexusrag.services.compliance.control_engine import (
    ControlEvaluationResult,
    evaluate_all_controls,
    get_latest_control_statuses,
)
from nexusrag.services.failover import get_failover_status
from nexusrag.services.governance import governance_evidence, governance_status_snapshot
from nexusrag.services.telemetry import counters_snapshot, gauges_snapshot


@dataclass(frozen=True)
class EvidenceBundleResult:
    bundle_id: int
    status: str
    manifest_uri: str | None
    signature: str | None
    checksum_sha256: str | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _evidence_dir() -> Path:
    settings = get_settings()
    base = Path(settings.compliance_evidence_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _signing_key() -> bytes:
    settings = get_settings()
    if not settings.backup_signing_key:
        raise ValueError("BACKUP_SIGNING_KEY is required for compliance signatures")
    return settings.backup_signing_key.encode("utf-8")


def _manifest_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sign_manifest(payload: dict[str, Any]) -> str:
    return hmac.new(_signing_key(), _manifest_bytes(payload), hashlib.sha256).hexdigest()


def verify_manifest(payload: dict[str, Any], signature: str) -> bool:
    expected = sign_manifest(payload)
    return hmac.compare_digest(expected, signature)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_snapshot() -> dict[str, Any]:
    settings = get_settings()
    # Keep config evidence limited to control-relevant settings.
    return {
        "compliance_enabled": settings.compliance_enabled,
        "compliance_default_window_days": settings.compliance_default_window_days,
        "compliance_eval_cron": settings.compliance_eval_cron,
        "compliance_bundle_cron": settings.compliance_bundle_cron,
        "compliance_evidence_retention_days": settings.compliance_evidence_retention_days,
        "compliance_signature_required": settings.compliance_signature_required,
        "backup_enabled": settings.backup_enabled,
        "backup_retention_days": settings.backup_retention_days,
        "crypto_enabled": settings.crypto_enabled,
        "region_id": settings.region_id,
        "region_role": settings.region_role,
    }


def _runbook_versions() -> list[dict[str, Any]]:
    runbook_dir = Path("docs") / "runbooks"
    entries: list[dict[str, Any]] = []
    if not runbook_dir.exists():
        return entries
    for path in sorted(runbook_dir.glob("*.md")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(
            {
                "path": str(path),
                "checksum_sha256": digest,
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return entries


async def _audit_summary(
    session: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    tenant_scope: str | None,
) -> dict[str, int]:
    query = select(AuditEvent.event_type, func.count()).where(
        AuditEvent.occurred_at >= window_start,
        AuditEvent.occurred_at <= window_end,
    )
    if tenant_scope is not None:
        query = query.where(AuditEvent.tenant_id == tenant_scope)
    query = query.group_by(AuditEvent.event_type)
    rows = (await session.execute(query)).all()
    return {row[0]: int(row[1] or 0) for row in rows}


async def _collect_evaluations(
    session: AsyncSession,
    *,
    tenant_scope: str | None,
    period_start: datetime,
    period_end: datetime,
    window_days: int,
) -> list[ControlEvaluationResult]:
    # Ensure evaluations exist for the bundle window, falling back to on-demand evaluation.
    evaluations = await evaluate_all_controls(
        session,
        window_days=window_days,
        tenant_scope=tenant_scope,
    )
    return evaluations


async def generate_evidence_bundle(
    session: AsyncSession,
    *,
    bundle_type: str,
    period_start: datetime,
    period_end: datetime,
    tenant_scope: str | None,
    generated_by_actor_id: str | None,
) -> EvidenceBundleResult:
    settings = get_settings()
    if not settings.compliance_enabled:
        raise ValueError("Compliance bundle generation is disabled")
    if settings.compliance_signature_required and not settings.backup_signing_key:
        raise ValueError("BACKUP_SIGNING_KEY is required for compliance signatures")

    bundle = EvidenceBundle(
        bundle_type=bundle_type,
        period_start=period_start,
        period_end=period_end,
        status="building",
        manifest_uri=None,
        signature=None,
        checksum_sha256=None,
        generated_by_actor_id=generated_by_actor_id,
        generated_at=None,
        expires_at=None,
        metadata_json=None,
    )
    session.add(bundle)
    await session.commit()
    await session.refresh(bundle)

    window_days = max(1, (period_end - period_start).days or settings.compliance_default_window_days)
    evaluations = await _collect_evaluations(
        session,
        tenant_scope=tenant_scope,
        period_start=period_start,
        period_end=period_end,
        window_days=window_days,
    )
    audit_summary = await _audit_summary(
        session,
        window_start=period_start,
        window_end=period_end,
        tenant_scope=tenant_scope,
    )
    governance_snapshot = await governance_status_snapshot(session, tenant_scope or "system")
    governance_bundle = await governance_evidence(
        session,
        tenant_id=tenant_scope or "system",
        window_days=window_days,
    )
    failover_snapshot = await get_failover_status(session)
    config_snapshot = _config_snapshot()
    config_checksum = hashlib.sha256(_manifest_bytes(config_snapshot)).hexdigest()

    manifest = {
        "bundle_id": bundle.id,
        "bundle_type": bundle_type,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "generated_at": _utc_now().isoformat(),
        "control_statuses": await get_latest_control_statuses(session, tenant_scope=tenant_scope),
        "evaluations": [
            {
                "control_id": evaluation.control_id,
                "status": evaluation.status,
                "score": evaluation.score,
                "evaluated_at": evaluation.evaluated_at.isoformat(),
                "findings": evaluation.findings,
            }
            for evaluation in evaluations
        ],
        "audit_summary": audit_summary,
        "governance": {
            "status": governance_snapshot,
            "evidence": {
                "retention_runs": governance_bundle.retention_runs,
                "dsar_requests": governance_bundle.dsar_requests,
                "legal_holds": governance_bundle.legal_holds,
                "policy_changes": governance_bundle.policy_changes,
            },
        },
        "failover": failover_snapshot,
        "config_checksum": config_checksum,
        "runbooks": _runbook_versions(),
        "telemetry": {
            "counters": counters_snapshot(),
            "gauges": gauges_snapshot(),
        },
    }

    evidence_dir = _evidence_dir() / f"bundle_{bundle.id}"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = evidence_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    evidence_path = evidence_dir / "evidence.json"
    evidence_payload = {
        "bundle_id": bundle.id,
        "audit_summary": audit_summary,
        "governance_status": governance_snapshot,
        "failover_status": failover_snapshot,
    }
    evidence_path.write_text(json.dumps(evidence_payload, indent=2, sort_keys=True), encoding="utf-8")

    bundle_path = evidence_dir / "bundle.tar.gz"
    with tarfile.open(bundle_path, "w:gz") as tar:
        tar.add(manifest_path, arcname="manifest.json")
        tar.add(evidence_path, arcname="evidence.json")

    checksum = _sha256_file(bundle_path)
    signature = sign_manifest(manifest) if settings.compliance_signature_required else None
    if signature:
        signature_path = evidence_dir / "signature.sig"
        signature_path.write_text(signature, encoding="utf-8")

    bundle.status = "ready"
    bundle.manifest_uri = str(bundle_path)
    bundle.signature = signature
    bundle.checksum_sha256 = checksum
    bundle.generated_at = _utc_now()
    bundle.expires_at = _utc_now() + timedelta(days=settings.compliance_evidence_retention_days)
    bundle.metadata_json = {"config_checksum": config_checksum}
    await session.commit()
    await session.refresh(bundle)

    return EvidenceBundleResult(
        bundle_id=bundle.id,
        status=bundle.status,
        manifest_uri=bundle.manifest_uri,
        signature=bundle.signature,
        checksum_sha256=bundle.checksum_sha256,
    )


async def verify_evidence_bundle(
    session: AsyncSession,
    *,
    bundle_id: int,
) -> tuple[bool, str]:
    bundle = await session.get(EvidenceBundle, bundle_id)
    if bundle is None or not bundle.manifest_uri:
        return False, "bundle not found"
    bundle_path = Path(bundle.manifest_uri)
    if not bundle_path.exists():
        return False, "bundle file missing"

    checksum = _sha256_file(bundle_path)
    if bundle.checksum_sha256 and checksum != bundle.checksum_sha256:
        return False, "checksum mismatch"

    with tarfile.open(bundle_path, "r:gz") as tar:
        manifest_member = tar.getmember("manifest.json")
        manifest_bytes = tar.extractfile(manifest_member).read() if manifest_member else None
    if not manifest_bytes:
        return False, "manifest missing"
    manifest_payload = json.loads(manifest_bytes.decode("utf-8"))

    if bundle.signature:
        if not verify_manifest(manifest_payload, bundle.signature):
            return False, "signature mismatch"
    elif get_settings().compliance_signature_required:
        return False, "signature missing"

    return True, "verified"
