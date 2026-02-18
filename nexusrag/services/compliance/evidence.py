from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
from uuid import uuid4
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import ComplianceSnapshot
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
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_excerpt(path: str, *, max_lines: int = 80) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:max_lines]).strip()


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


async def create_compliance_snapshot(
    session: AsyncSession,
    *,
    tenant_id: str,
    created_by: str | None,
) -> ComplianceSnapshot:
    # Persist deterministic compliance posture snapshots for SOC2-style evidence exports.
    status, controls = await evaluate_controls(session)
    counts = {
        "pass": sum(1 for item in controls if item["status"] == "pass"),
        "degraded": sum(1 for item in controls if item["status"] == "degraded"),
        "fail": sum(1 for item in controls if item["status"] == "fail"),
    }
    summary = {
        "status": status,
        "counts": counts,
        "generated_at": _utc_now().isoformat(),
    }
    row = ComplianceSnapshot(
        id=uuid4().hex,
        tenant_id=tenant_id,
        created_by=created_by,
        status=status,
        summary_json=summary,
        controls_json=controls,
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
            .order_by(ComplianceSnapshot.created_at.desc())
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


def build_bundle_archive(snapshot: ComplianceSnapshot) -> bytes:
    # Build an in-memory zip so compliance bundles are deterministic and easy to export.
    payload_snapshot = {
        "id": snapshot.id,
        "tenant_id": snapshot.tenant_id,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "created_by": snapshot.created_by,
        "status": snapshot.status,
        "summary_json": snapshot.summary_json,
    }
    controls = snapshot.controls_json or []
    config_sanitized = sanitize_config_snapshot()
    runbooks = _runbooks_index()
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
    return buffer.getvalue()


def required_bundle_files() -> tuple[str, ...]:
    return _REQUIRED_BUNDLE_FILES
