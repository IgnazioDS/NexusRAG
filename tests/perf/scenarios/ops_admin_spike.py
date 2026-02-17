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
    make_client,
    perf_report_dir,
    run_with_concurrency,
)


async def _run_batch(*, tenants: list[TenantContext], client, scenario: str) -> list[Any]:
    # Spike admin ops endpoints to validate control-plane responsiveness.
    jobs = []
    for tenant in tenants:
        for path in ["/v1/ops/health", "/v1/ops/metrics", "/v1/ops/slo", "/v1/ops/ingestion?hours=1"]:
            jobs.append(
                lambda tenant=tenant, path=path: execute_request(
                    client=client,
                    scenario=scenario,
                    tenant=tenant,
                    method="GET",
                    path=path,
                    route_class="ops",
                    headers=tenant.admin_headers,
                )
            )
    return await run_with_concurrency(workers=6, jobs=jobs)


async def run_scenario(*, duration: int, deterministic: bool) -> dict[str, Any]:
    # Run short ops/admin spikes and emit deterministic latency/error summaries.
    scenario = "ops_admin_spike"
    configure_perf_environment(deterministic=deterministic)
    tenants = await bootstrap_tenants(
        fixture_path=Path("tests/perf/fixtures/tenants.json"),
        scenario_name=scenario,
    )
    request_records = []
    stream_records = []
    deadline = time.monotonic() + max(1, duration)

    async with make_client() as client:
        while time.monotonic() < deadline:
            request_records.extend(await _run_batch(tenants=tenants, client=client, scenario=scenario))
            await asyncio.sleep(0)

    summary = summarize_records(records=request_records, stream_records=stream_records)
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
    parser = argparse.ArgumentParser(description="Run admin ops spike scenario")
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--deterministic", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_scenario(duration=args.duration, deterministic=args.deterministic))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
