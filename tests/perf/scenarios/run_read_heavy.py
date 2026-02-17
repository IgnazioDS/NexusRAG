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
    TenantContext,
    bootstrap_tenants,
    configure_perf_environment,
    execute_request,
    execute_run_stream,
    make_client,
    memory_usage_mb,
    perf_report_dir,
    run_with_concurrency,
)


async def _run_batch(*, tenants: list[TenantContext], client, scenario: str) -> tuple[list[Any], list[Any]]:
    # Run a read-heavy batch with mostly /run requests and a light metadata load.
    jobs = []
    for tenant in tenants:
        for idx in range(3):
            jobs.append(
                lambda tenant=tenant, idx=idx: execute_run_stream(
                    client=client,
                    scenario=scenario,
                    tenant=tenant,
                    message=f"perf read-heavy question {idx}",
                    top_k=5,
                    audio=False,
                )
            )
        jobs.append(
            lambda tenant=tenant: execute_request(
                client=client,
                scenario=scenario,
                tenant=tenant,
                method="GET",
                path="/v1/documents",
                route_class="read",
                headers=tenant.reader_headers,
            )
        )
    results = await run_with_concurrency(workers=8, jobs=jobs)
    request_records = []
    stream_records = []
    for item in results:
        if isinstance(item, tuple):
            request_records.append(item[0])
            stream_records.append(item[1])
        else:
            request_records.append(item)
    return request_records, stream_records


async def run_scenario(*, duration: int, deterministic: bool) -> dict[str, Any]:
    # Execute the read-heavy scenario for a fixed duration with deterministic setup.
    scenario = "run_read_heavy"
    configure_perf_environment(deterministic=deterministic)
    tenants = await bootstrap_tenants(
        fixture_path=Path("tests/perf/fixtures/tenants.json"),
        scenario_name=scenario,
    )
    started_mem = memory_usage_mb()
    request_records = []
    stream_records = []
    deadline = time.monotonic() + max(1, duration)
    async with make_client() as client:
        while time.monotonic() < deadline:
            batch_records, batch_streams = await _run_batch(tenants=tenants, client=client, scenario=scenario)
            request_records.extend(batch_records)
            stream_records.extend(batch_streams)
            await asyncio.sleep(0)
        # Query ops metrics once for queue/saturation snapshots.
        metrics_response = await client.get("/v1/ops/metrics", headers=tenants[0].admin_headers)
        metrics_payload = metrics_response.json().get("data", {}) if metrics_response.status_code == 200 else {}

    ending_mem = memory_usage_mb()
    summary = summarize_records(
        records=request_records,
        stream_records=stream_records,
        extra={
            "memory_growth_mb": max(0.0, ending_mem - started_mem),
            "queue_depth": ((metrics_payload.get("gauges") or {}).get("nexusrag_ingest_queue_depth")),
            "db_pool": metrics_payload.get("db_pool", {}),
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
    parser = argparse.ArgumentParser(description="Run read-heavy /v1/run performance scenario")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--deterministic", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_scenario(duration=args.duration, deterministic=args.deterministic))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
