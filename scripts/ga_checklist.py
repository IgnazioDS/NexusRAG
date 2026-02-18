from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import text

from nexusrag.core.config import get_settings
from nexusrag.persistence.db import SessionLocal


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _check_perf_gates() -> dict[str, Any]:
    settings = get_settings()
    gate_file = Path("tests/perf/assert_perf_gates.py")
    passed = gate_file.exists() and settings.perf_run_target_p95_ms > 0 and settings.perf_max_error_rate >= 0.0
    return {
        "category": "perf_gates",
        "status": "pass" if passed else "fail",
        "detail": {
            "gate_file": str(gate_file),
            "exists": gate_file.exists(),
            "perf_run_target_p95_ms": settings.perf_run_target_p95_ms,
            "perf_max_error_rate": settings.perf_max_error_rate,
        },
    }


def _check_capacity_model() -> dict[str, Any]:
    model_path = Path("docs/capacity-model.md")
    return {
        "category": "capacity_model",
        "status": "pass" if model_path.exists() else "fail",
        "detail": {"path": str(model_path), "exists": model_path.exists()},
    }


def _check_security_targets() -> dict[str, Any]:
    makefile = Path("Makefile")
    text_body = makefile.read_text(encoding="utf-8") if makefile.exists() else ""
    required = ("security-audit", "security-lint", "security-secrets-scan")
    missing = [target for target in required if f"{target}:" not in text_body]
    return {
        "category": "security_targets",
        "status": "pass" if not missing else "fail",
        "detail": {"missing": missing},
    }


async def _check_retention_state() -> dict[str, Any]:
    settings = get_settings()
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT task, MAX(last_run_at) AS last_run_at "
                    "FROM retention_runs GROUP BY task"
                )
            )
        ).all()
    last_run = {row[0]: row[1].isoformat() if row[1] else None for row in rows}
    configured = (
        settings.audit_retention_days > 0
        and settings.usage_counter_retention_days > 0
        and settings.ui_action_retention_days > 0
    )
    status = "pass" if configured else "fail"
    return {
        "category": "retention",
        "status": status,
        "detail": {
            "audit_retention_days": settings.audit_retention_days,
            "usage_counter_retention_days": settings.usage_counter_retention_days,
            "ui_action_retention_days": settings.ui_action_retention_days,
            "last_run": last_run,
        },
    }


async def _check_dr_readiness() -> dict[str, Any]:
    settings = get_settings()
    async with SessionLocal() as session:
        backup = (
            await session.execute(
                text(
                    "SELECT completed_at, status FROM backup_jobs "
                    "WHERE status = 'succeeded' ORDER BY completed_at DESC LIMIT 1"
                )
            )
        ).first()
        drill = (
            await session.execute(
                text(
                    "SELECT completed_at, status FROM restore_drills "
                    "ORDER BY completed_at DESC LIMIT 1"
                )
            )
        ).first()
    status = "pass" if settings.failover_enabled and settings.backup_enabled else "fail"
    return {
        "category": "dr_readiness",
        "status": status,
        "detail": {
            "failover_enabled": settings.failover_enabled,
            "backup_enabled": settings.backup_enabled,
            "last_backup": {
                "completed_at": backup[0].isoformat() if backup and backup[0] else None,
                "status": backup[1] if backup else None,
            },
            "last_restore_drill": {
                "completed_at": drill[0].isoformat() if drill and drill[0] else None,
                "status": drill[1] if drill else None,
            },
        },
    }


async def _check_alerting_automation() -> dict[str, Any]:
    settings = get_settings()
    async with SessionLocal() as session:
        enabled_rules = (
            await session.execute(
                text("SELECT COUNT(*) FROM alert_rules WHERE enabled = true")
            )
        ).scalar_one_or_none()
    has_rules = int(enabled_rules or 0) > 0
    passed = settings.alerting_enabled and settings.incident_automation_enabled and has_rules
    return {
        "category": "alerting_incident_automation",
        "status": "pass" if passed else "fail",
        "detail": {
            "alerting_enabled": settings.alerting_enabled,
            "incident_automation_enabled": settings.incident_automation_enabled,
            "enabled_rule_count": int(enabled_rules or 0),
        },
    }


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# GA Readiness Checklist",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- status: {payload['status']}",
        "",
        "| Category | Status |",
        "| --- | --- |",
    ]
    for item in payload["checks"]:
        lines.append(f"| {item['category']} | {item['status']} |")
    lines.append("")
    lines.append("## Details")
    lines.append("")
    for item in payload["checks"]:
        lines.append(f"### {item['category']}")
        lines.append("```json")
        lines.append(json.dumps(item["detail"], indent=2, sort_keys=True))
        lines.append("```")
    return "\n".join(lines)


async def run_checklist(*, output_dir: str | None) -> int:
    settings = get_settings()
    checks = [
        _check_perf_gates(),
        _check_capacity_model(),
        _check_security_targets(),
        await _check_retention_state(),
        await _check_dr_readiness(),
        await _check_alerting_automation(),
    ]
    status = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    generated_at = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "generated_at": generated_at,
        "status": status,
        "checks": checks,
    }
    output_root = Path(output_dir or settings.ga_checklist_output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / f"ga-checklist-{generated_at}.json"
    md_path = output_root / f"ga-checklist-{generated_at}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(payload), encoding="utf-8")
    print(json.dumps({"status": status, "json": str(json_path), "markdown": str(md_path)}, indent=2))
    return 0 if status == "pass" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate GA readiness checklist artifacts.")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    return asyncio.run(run_checklist(output_dir=args.output_dir))


if __name__ == "__main__":
    sys.exit(main())
