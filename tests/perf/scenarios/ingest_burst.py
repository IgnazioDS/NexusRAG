from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    # Ensure local package imports work when invoked as a script path.
    sys.path.insert(0, str(ROOT_DIR))

from tests.perf.utils.metrics_capture import summarize_records, write_report
from tests.perf.utils.workload import (
    TenantContext,
    RequestRecord,
    bootstrap_tenants,
    configure_perf_environment,
    make_client,
    memory_usage_mb,
    perf_report_dir,
    run_with_concurrency,
)


def _parse_ts(value: str | None) -> datetime | None:
    # Parse ISO8601 timestamps from document lifecycle fields.
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _post_ingest(
    *,
    client,
    scenario: str,
    tenant: TenantContext,
    suffix: str,
) -> tuple[RequestRecord, str | None]:
    # Send one ingestion request and return the accepted document id.
    started = time.monotonic()
    response = await client.post(
        "/v1/documents/text",
        headers=tenant.admin_headers,
        json={
            "corpus_id": tenant.corpus_id,
            "text": f"perf ingest burst payload {suffix}",
            "document_id": f"d-ingest-{suffix}",
            "filename": "ingest.txt",
        },
    )
    latency_ms = (time.monotonic() - started) * 1000.0
    payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    error_payload = payload.get("error", {}) if isinstance(payload, dict) else {}
    error_code = error_payload.get("code") if isinstance(error_payload, dict) else None
    request_record = RequestRecord(
        scenario=scenario,
        tenant_id=tenant.tenant_id,
        tier=tenant.tier,
        route_class="ingest",
        method="POST",
        path="/v1/documents/text",
        status_code=int(response.status_code),
        latency_ms=latency_ms,
        timeout=False,
        error_code=error_code,
        degraded=response.headers.get("X-SLA-Decision") == "degrade",
        shed=error_code == "SLA_SHED_LOAD",
        rate_limited=error_code == "RATE_LIMITED",
        quota_exceeded=error_code in {"QUOTA_EXCEEDED", "COST_BUDGET_EXCEEDED"},
    )
    document_id: str | None = None
    if request_record.status_code in {200, 202}:
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        document_id = data.get("document_id") if isinstance(data, dict) else None
    return request_record, document_id


async def run_scenario(*, duration: int, deterministic: bool) -> dict[str, Any]:
    # Drive an ingestion burst and estimate queue wait percentiles from document lifecycle timestamps.
    scenario = "ingest_burst"
    configure_perf_environment(deterministic=deterministic)
    tenants = await bootstrap_tenants(
        fixture_path=Path("tests/perf/fixtures/tenants.json"),
        scenario_name=scenario,
    )
    started_mem = memory_usage_mb()
    request_records: list[RequestRecord] = []
    stream_records = []
    created_documents: list[tuple[TenantContext, str]] = []

    async with make_client() as client:
        jobs = []
        for index in range(max(1, duration // 2)):
            for tenant in tenants:
                suffix = f"{tenant.tier}-{index}-{uuid4().hex[:6]}"
                jobs.append(lambda tenant=tenant, suffix=suffix: _post_ingest(client=client, scenario=scenario, tenant=tenant, suffix=suffix))
        results = await run_with_concurrency(workers=10, jobs=jobs)
        for record, document_id in results:
            request_records.append(record)
            if document_id is not None:
                tenant = next(item for item in tenants if item.tenant_id == record.tenant_id)
                created_documents.append((tenant, document_id))

        queue_waits: list[float] = []
        processing_durations: list[float] = []
        for tenant, document_id in created_documents:
            # Poll document status briefly so inline mode and queued mode both contribute timings.
            for _ in range(8):
                response = await client.get(f"/v1/documents/{document_id}", headers=tenant.admin_headers)
                if response.status_code != 200:
                    break
                payload = response.json().get("data", {})
                queued_at = _parse_ts(payload.get("queued_at"))
                processing_started_at = _parse_ts(payload.get("processing_started_at"))
                completed_at = _parse_ts(payload.get("completed_at"))
                if queued_at and processing_started_at:
                    queue_waits.append((processing_started_at - queued_at).total_seconds() * 1000.0)
                if processing_started_at and completed_at:
                    processing_durations.append((completed_at - processing_started_at).total_seconds() * 1000.0)
                if payload.get("status") in {"succeeded", "failed"}:
                    break
                await asyncio.sleep(0.05)

        metrics_response = await client.get("/v1/ops/ingestion?hours=1", headers=tenants[0].admin_headers)
        metrics_payload = metrics_response.json().get("data", {}) if metrics_response.status_code == 200 else {}

    ending_mem = memory_usage_mb()
    queue_waits.sort()
    queue_wait_p95 = queue_waits[max(0, int(len(queue_waits) * 0.95) - 1)] if queue_waits else 0.0
    processing_durations.sort()
    processing_p95 = processing_durations[max(0, int(len(processing_durations) * 0.95) - 1)] if processing_durations else 0.0

    summary = summarize_records(
        records=request_records,
        stream_records=stream_records,
        extra={
            "memory_growth_mb": max(0.0, ending_mem - started_mem),
            "ingest_queue_wait_p95_ms": queue_wait_p95,
            "ingest_processing_p95_ms": processing_p95,
            "ops_ingestion": metrics_payload,
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
    parser = argparse.ArgumentParser(description="Run ingestion burst performance scenario")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--deterministic", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_scenario(duration=args.duration, deterministic=args.deterministic))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
