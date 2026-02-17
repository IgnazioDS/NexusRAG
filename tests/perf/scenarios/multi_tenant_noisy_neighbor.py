from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    # Ensure local package imports work when invoked as a script path.
    sys.path.insert(0, str(ROOT_DIR))

from tests.perf.utils.metrics_capture import summarize_records, write_report
from tests.perf.utils.workload import (
    RequestRecord,
    TenantContext,
    bootstrap_tenants,
    configure_perf_environment,
    execute_run_stream,
    make_client,
    perf_report_dir,
    run_with_concurrency,
)


async def _run_batch(*, tenants: list[TenantContext], client, scenario: str) -> tuple[list[RequestRecord], list[Any]]:
    # Stress one noisy tenant while preserving traffic for other tenants.
    noisy = tenants[0]
    others = tenants[1:]
    jobs = []
    for index in range(8):
        jobs.append(
            lambda noisy=noisy, index=index: execute_run_stream(
                client=client,
                scenario=scenario,
                tenant=noisy,
                message=f"noisy run {index}",
                top_k=5,
                audio=False,
            )
        )
    for tenant in others:
        for index in range(2):
            jobs.append(
                lambda tenant=tenant, index=index: execute_run_stream(
                    client=client,
                    scenario=scenario,
                    tenant=tenant,
                    message=f"sensitive run {index}",
                    top_k=5,
                    audio=False,
                )
            )
    results = await run_with_concurrency(workers=12, jobs=jobs)
    request_records: list[RequestRecord] = []
    stream_records: list[Any] = []
    for record, stream in results:
        request_records.append(record)
        stream_records.append(stream)
    return request_records, stream_records


def _success_rate(records: list[RequestRecord]) -> float:
    # Measure success as non-error terminal status for fairness checks.
    if not records:
        return 1.0
    successes = sum(1 for row in records if row.status_code < 400 and not row.timeout and row.status_code != 599)
    return successes / len(records)


async def run_scenario(*, duration: int, deterministic: bool) -> dict[str, Any]:
    # Validate noisy-neighbor fairness under asymmetric tenant traffic.
    scenario = "multi_tenant_noisy_neighbor"
    configure_perf_environment(deterministic=deterministic)
    tenants = await bootstrap_tenants(
        fixture_path=Path("tests/perf/fixtures/tenants.json"),
        scenario_name=scenario,
    )
    request_records: list[RequestRecord] = []
    stream_records = []
    deadline = time.monotonic() + max(1, duration)

    async with make_client() as client:
        while time.monotonic() < deadline:
            batch_records, batch_streams = await _run_batch(tenants=tenants, client=client, scenario=scenario)
            request_records.extend(batch_records)
            stream_records.extend(batch_streams)
            await asyncio.sleep(0)

    noisy_tenant_id = tenants[0].tenant_id
    noisy_records = [row for row in request_records if row.tenant_id == noisy_tenant_id]
    other_records = [row for row in request_records if row.tenant_id != noisy_tenant_id]
    noisy_success = _success_rate(noisy_records)
    other_success = _success_rate(other_records)
    fairness_ratio = (other_success / noisy_success) if noisy_success > 0 else 1.0

    summary = summarize_records(
        records=request_records,
        stream_records=stream_records,
        extra={
            "noisy_neighbor_success_ratio": fairness_ratio,
            "noisy_success_rate": noisy_success,
            "other_success_rate": other_success,
        },
    )
    json_path, md_path = write_report(
        report_dir=perf_report_dir(),
        scenario=scenario,
        duration_s=duration,
        deterministic=deterministic,
        summary=summary,
        records=request_records,
        stream_records=stream_records,
    )
    return {"scenario": scenario, "summary": summary, "json_report": str(json_path), "md_report": str(md_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run noisy-neighbor multi-tenant scenario")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--deterministic", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_scenario(duration=args.duration, deterministic=args.deterministic))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
