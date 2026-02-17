from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    # Ensure local package imports work when invoked as a script path.
    sys.path.insert(0, str(ROOT_DIR))

from tests.perf.utils.workload import perf_report_dir


def _latest_report_for_scenario(report_dir: Path, scenario: str) -> Path | None:
    # Select the latest JSON report artifact per scenario.
    candidates = sorted(report_dir.glob(f"{scenario}-*.json"))
    if not candidates:
        return None
    return candidates[-1]


def main() -> int:
    report_dir = perf_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    scenarios = [
        "run_read_heavy",
        "run_mixed",
        "ingest_burst",
        "ops_admin_spike",
        "multi_tenant_noisy_neighbor",
    ]

    lines = [
        "# Performance Summary",
        "",
        f"Generated at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| scenario | requests | error_rate | run_p95_ms | ingest_queue_wait_p95_ms | noisy_neighbor_ratio |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    for scenario in scenarios:
        latest = _latest_report_for_scenario(report_dir, scenario)
        if latest is None:
            lines.append(f"| {scenario} | 0 | 0 | 0 | 0 | 0 |")
            continue
        payload = json.loads(latest.read_text(encoding="utf-8"))
        summary = payload.get("summary") or {}
        overall = summary.get("overall") or {}
        route_run = (summary.get("route_class") or {}).get("run") or {}
        extra = summary.get("extra") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    scenario,
                    str(overall.get("requests", 0)),
                    f"{float(overall.get('error_rate', 0.0)):.4f}",
                    f"{float(route_run.get('p95_ms') or 0.0):.2f}",
                    f"{float(extra.get('ingest_queue_wait_p95_ms') or 0.0):.2f}",
                    f"{float(extra.get('noisy_neighbor_success_ratio') or 0.0):.4f}",
                ]
            )
            + " |"
        )

    output_path = report_dir / "perf-summary-latest.md"
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
