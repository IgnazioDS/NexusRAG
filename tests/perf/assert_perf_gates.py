from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    # Ensure local package imports work when invoked as a script path.
    sys.path.insert(0, str(ROOT_DIR))

from nexusrag.core.config import get_settings
from tests.perf.scenarios.ingest_burst import run_scenario as run_ingest_burst
from tests.perf.scenarios.multi_tenant_noisy_neighbor import run_scenario as run_noisy_neighbor
from tests.perf.scenarios.ops_admin_spike import run_scenario as run_ops_spike
from tests.perf.scenarios.run_mixed import run_scenario as run_mixed
from tests.perf.scenarios.run_read_heavy import run_scenario as run_read_heavy
from tests.perf.utils.assertions import PerfGateThresholds, evaluate_perf_gates
from tests.perf.utils.metrics_capture import summarize_records
from tests.perf.utils.workload import RequestRecord, StreamRecord, perf_report_dir


def _records_from_payload(payload: dict[str, Any]) -> tuple[list[RequestRecord], list[StreamRecord]]:
    # Rehydrate report payloads into typed records for aggregate summaries.
    request_records = [RequestRecord(**row) for row in payload.get("records", [])]
    stream_records = [StreamRecord(**row) for row in payload.get("stream_records", [])]
    return request_records, stream_records


async def _run_scenarios(*, duration: int, deterministic: bool) -> list[dict[str, Any]]:
    # Execute required perf scenarios in deterministic order for reproducible gates.
    return [
        await run_read_heavy(duration=duration, deterministic=deterministic),
        await run_mixed(duration=duration, deterministic=deterministic),
        await run_ingest_burst(duration=duration, deterministic=deterministic),
        await run_ops_spike(duration=max(30, duration // 2), deterministic=deterministic),
        await run_noisy_neighbor(duration=duration, deterministic=deterministic),
    ]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic perf scenarios and enforce gates")
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--from-reports", action="store_true", help="evaluate existing JSON reports only")
    args = parser.parse_args()

    settings = get_settings()
    report_dir = perf_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)

    scenario_results: list[dict[str, Any]]
    if args.from_reports:
        json_reports = sorted(report_dir.glob("*.json"))
        scenario_results = [{"json_report": str(path)} for path in json_reports]
    else:
        scenario_results = await _run_scenarios(duration=args.duration, deterministic=args.deterministic)

    all_records: list[RequestRecord] = []
    all_stream_records: list[StreamRecord] = []
    extra: dict[str, Any] = {}
    for result in scenario_results:
        json_path = Path(result["json_report"])
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        records, stream_records = _records_from_payload(payload)
        all_records.extend(records)
        all_stream_records.extend(stream_records)
        summary_extra = (payload.get("summary") or {}).get("extra") or {}
        # Preserve the most conservative signals for gate evaluation.
        if "ingest_queue_wait_p95_ms" in summary_extra:
            extra["ingest_queue_wait_p95_ms"] = max(
                float(extra.get("ingest_queue_wait_p95_ms", 0.0)),
                float(summary_extra["ingest_queue_wait_p95_ms"]),
            )
        if "memory_growth_mb" in summary_extra:
            extra["memory_growth_mb"] = max(
                float(extra.get("memory_growth_mb", 0.0)),
                float(summary_extra["memory_growth_mb"]),
            )
        if "noisy_neighbor_success_ratio" in summary_extra:
            extra["noisy_neighbor_success_ratio"] = float(summary_extra["noisy_neighbor_success_ratio"])

    aggregate = summarize_records(records=all_records, stream_records=all_stream_records, extra=extra)
    thresholds = PerfGateThresholds(
        run_p95_ms_max=float(settings.perf_run_target_p95_ms),
        max_error_rate=float(settings.perf_max_error_rate),
        max_ingest_queue_wait_p95_ms=float(settings.perf_run_target_p95_ms) * 2.0,
        max_memory_growth_mb=256.0,
        min_noisy_neighbor_success_ratio=0.75,
    )
    violations = evaluate_perf_gates(aggregate=aggregate, thresholds=thresholds)

    output = {
        "aggregate": aggregate,
        "thresholds": asdict(thresholds),
        "violations": violations,
        "reports": [result["json_report"] for result in scenario_results],
    }
    output_path = report_dir / "perf-gates-latest.json"
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True))

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
