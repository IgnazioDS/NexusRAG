from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from uuid import uuid4
import zipfile

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import AuditEvent, ComplianceSnapshot
from nexusrag.services.audit import sanitize_metadata
from nexusrag.services.compliance.controls import evaluate_controls


_REQUIRED_BUNDLE_FILES = (
    "snapshot.json",
    "controls.json",
    "config_sanitized.json",
    "runbooks_index.json",
    "changelog_excerpt.md",
    "capacity_model_excerpt.md",
    "perf_gates_excerpt.json",
    "perf_report_summary.md",
    "ops_metrics_24h_summary.json",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot_captured_at(snapshot: ComplianceSnapshot) -> datetime:
    # Keep canonical timestamp stable while tolerating legacy rows that only have created_at.
    return snapshot.captured_at or snapshot.created_at or _utc_now()


def _snapshot_results(snapshot: ComplianceSnapshot) -> dict[str, object]:
    # Serve canonical results_json while preserving compatibility with legacy summary/controls-only rows.
    if snapshot.results_json is not None:
        return snapshot.results_json
    return {
        "summary": snapshot.summary_json,
        "controls": snapshot.controls_json,
    }


def _read_excerpt(path: str, *, max_lines: int = 80) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:max_lines]).strip()


def _latest_perf_report_summary() -> str:
    # Export the latest deterministic perf report so compliance bundles include performance evidence.
    report_dir = Path(get_settings().perf_report_dir)
    if not report_dir.exists():
        return ""
    candidates = sorted(report_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return ""
    return _read_excerpt(str(candidates[0]), max_lines=120)


def sanitize_config_snapshot() -> dict[str, object]:
    # Redact sensitive settings keys while preserving compliance-relevant structure.
    raw = get_settings().model_dump()
    sanitized = sanitize_metadata(raw)

    def _redact_explicit(value: object) -> object:
        if isinstance(value, dict):
            redacted: dict[str, object] = {}
            for key, item in value.items():
                lowered = key.lower()
                if any(
                    marker in lowered
                    for marker in (
                        "api_key",
                        "secret",
                        "password",
                        "token",
                        "signing_key",
                        "master_key",
                        "private_key",
                    )
                ):
                    redacted[key] = "[REDACTED]"
                else:
                    redacted[key] = _redact_explicit(item)
            return redacted
        if isinstance(value, list):
            return [_redact_explicit(item) for item in value]
        return value

    redacted = _redact_explicit(sanitized)
    return redacted if isinstance(redacted, dict) else {}


def _runbooks_index() -> list[str]:
    runbook_dir = Path("docs/runbooks")
    if not runbook_dir.exists():
        return []
    return [str(path) for path in sorted(runbook_dir.glob("*.md"))]


async def _ops_metrics_summary_24h(session: AsyncSession, *, tenant_id: str | None) -> dict[str, object]:
    # Build a compact 24h audit-derived ops summary without storing sensitive request payloads.
    window_end = _utc_now()
    window_start = window_end - timedelta(hours=24)

    filters = [AuditEvent.occurred_at >= window_start, AuditEvent.occurred_at <= window_end]
    if tenant_id is not None:
        filters.append(AuditEvent.tenant_id == tenant_id)
    totals = (
        await session.execute(
            select(
                func.count(AuditEvent.id),
                func.sum(case((AuditEvent.outcome == "failure", 1), else_=0)),
            ).where(*filters)
        )
    ).one()
    by_event_rows = (
        await session.execute(
            select(AuditEvent.event_type, func.count(AuditEvent.id))
            .where(*filters)
            .group_by(AuditEvent.event_type)
            .order_by(func.count(AuditEvent.id).desc())
            .limit(10)
        )
    ).all()
    total_events = int(totals[0] or 0)
    failure_events = int(totals[1] or 0)
    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "total_events": total_events,
        "failure_events": failure_events,
        "failure_rate": round((failure_events / total_events), 6) if total_events else 0.0,
        "top_event_types": [{"event_type": row[0], "count": int(row[1])} for row in by_event_rows],
    }


async def create_compliance_snapshot(
    session: AsyncSession,
    *,
    tenant_id: str,
    created_by: str | None,
) -> ComplianceSnapshot:
    # Persist deterministic compliance posture snapshots for SOC2-style evidence exports.
    captured_at = _utc_now()
    status, controls = await evaluate_controls(session)
    counts = {
        "pass": sum(1 for item in controls if item["status"] == "pass"),
        "degraded": sum(1 for item in controls if item["status"] == "degraded"),
        "fail": sum(1 for item in controls if item["status"] == "fail"),
    }
    summary = {
        "status": status,
        "counts": counts,
        "generated_at": captured_at.isoformat(),
    }
    row = ComplianceSnapshot(
        id=uuid4().hex,
        tenant_id=tenant_id,
        captured_at=captured_at,
        created_by=created_by,
        status=status,
        results_json={"summary": summary, "controls": controls},
        summary_json=summary,
        controls_json=controls,
        artifact_paths_json={},
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_compliance_snapshots(
    session: AsyncSession,
    *,
    tenant_id: str,
    limit: int,
) -> list[ComplianceSnapshot]:
    rows = (
        await session.execute(
            select(ComplianceSnapshot)
            .where(ComplianceSnapshot.tenant_id == tenant_id)
            .order_by(func.coalesce(ComplianceSnapshot.captured_at, ComplianceSnapshot.created_at).desc())
            .limit(max(1, min(limit, 200)))
        )
    ).scalars().all()
    return list(rows)


async def get_compliance_snapshot(
    session: AsyncSession,
    *,
    tenant_id: str,
    snapshot_id: str,
) -> ComplianceSnapshot | None:
    row = await session.get(ComplianceSnapshot, snapshot_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


async def build_bundle_archive(session: AsyncSession, snapshot: ComplianceSnapshot) -> bytes:
    # Build and persist evidence bundles so operators can export/re-check artifacts deterministically.
    captured_at = _snapshot_captured_at(snapshot)
    results_json = _snapshot_results(snapshot)
    payload_snapshot = {
        "id": snapshot.id,
        "tenant_id": snapshot.tenant_id,
        "captured_at": captured_at.isoformat(),
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "created_by": snapshot.created_by,
        "status": snapshot.status,
        "results_json": results_json,
        "summary_json": snapshot.summary_json,
        "artifact_paths_json": snapshot.artifact_paths_json or {},
    }
    controls = snapshot.controls_json or []
    config_sanitized = sanitize_config_snapshot()
    runbooks = _runbooks_index()
    ops_metrics = await _ops_metrics_summary_24h(session, tenant_id=snapshot.tenant_id)
    perf_report_summary = _latest_perf_report_summary()
    perf_excerpt = {
        "perf_run_target_p95_ms": get_settings().perf_run_target_p95_ms,
        "perf_max_error_rate": get_settings().perf_max_error_rate,
        "perf_soak_duration_min": get_settings().perf_soak_duration_min,
        "perf_gate_script_present": Path("tests/perf/assert_perf_gates.py").exists(),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("snapshot.json", json.dumps(payload_snapshot, indent=2, sort_keys=True))
        archive.writestr("controls.json", json.dumps(controls, indent=2, sort_keys=True))
        archive.writestr("config_sanitized.json", json.dumps(config_sanitized, indent=2, sort_keys=True))
        archive.writestr("runbooks_index.json", json.dumps(runbooks, indent=2, sort_keys=True))
        archive.writestr("changelog_excerpt.md", _read_excerpt("CHANGELOG.md"))
        archive.writestr("capacity_model_excerpt.md", _read_excerpt("docs/capacity-model.md"))
        archive.writestr("perf_gates_excerpt.json", json.dumps(perf_excerpt, indent=2, sort_keys=True))
        archive.writestr("perf_report_summary.md", perf_report_summary)
        archive.writestr("ops_metrics_24h_summary.json", json.dumps(ops_metrics, indent=2, sort_keys=True))
    payload = buffer.getvalue()
    evidence_dir = Path(get_settings().compliance_evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    # Persist generated bundles under var/evidence for deterministic operator retrieval.
    bundle_path = evidence_dir / f"{snapshot.id}.zip"
    bundle_path.write_bytes(payload)
    snapshot.artifact_paths_json = {
        **(snapshot.artifact_paths_json or {}),
        "bundle_path": str(bundle_path),
        "bundle_download_path": f"/v1/admin/compliance/snapshots/{snapshot.id}/download",
        "bundle_generated_at": _utc_now().isoformat(),
    }
    await session.commit()
    await session.refresh(snapshot)
    return payload


def required_bundle_files() -> tuple[str, ...]:
    return _REQUIRED_BUNDLE_FILES
