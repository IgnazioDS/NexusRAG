from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tests.perf.utils.workload import RequestRecord, StreamRecord


def _percentile(values: list[float], q: float) -> float | None:
    # Use nearest-rank percentile for deterministic gate behavior.
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(q * len(ordered)) - 1)
    return float(ordered[index])


def summarize_records(
    *,
    records: list[RequestRecord],
    stream_records: list[StreamRecord],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Build a stable summary used by perf gates and report artifacts.
    total = len(records)
    errors = [r for r in records if r.status_code >= 400 or r.status_code == 599 or r.timeout]
    grouped_route: dict[str, list[RequestRecord]] = defaultdict(list)
    grouped_tier: dict[str, list[RequestRecord]] = defaultdict(list)
    for record in records:
        grouped_route[record.route_class].append(record)
        grouped_tier[record.tier].append(record)

    route_summary: dict[str, Any] = {}
    for route_class, rows in grouped_route.items():
        latencies = [row.latency_ms for row in rows]
        errors_count = sum(1 for row in rows if row.status_code >= 400 or row.status_code == 599 or row.timeout)
        route_summary[route_class] = {
            "count": len(rows),
            "p50_ms": _percentile(latencies, 0.50),
            "p95_ms": _percentile(latencies, 0.95),
            "p99_ms": _percentile(latencies, 0.99),
            "error_rate": (errors_count / len(rows)) if rows else 0.0,
            "shed_count": sum(1 for row in rows if row.shed),
            "degrade_count": sum(1 for row in rows if row.degraded),
            "rate_limited_count": sum(1 for row in rows if row.rate_limited),
            "quota_count": sum(1 for row in rows if row.quota_exceeded),
        }

    tier_summary: dict[str, Any] = {}
    for tier, rows in grouped_tier.items():
        latencies = [row.latency_ms for row in rows]
        tier_summary[tier] = {
            "count": len(rows),
            "p95_ms": _percentile(latencies, 0.95),
            "error_rate": (sum(1 for row in rows if row.status_code >= 400 or row.status_code == 599 or row.timeout) / len(rows))
            if rows
            else 0.0,
        }

    first_token = [record.first_token_latency_ms for record in stream_records if record.first_token_latency_ms is not None]
    completion = [record.completion_latency_ms for record in stream_records]
    sse_summary = {
        "streams": len(stream_records),
        "first_token_p50_ms": _percentile(first_token, 0.50),
        "first_token_p95_ms": _percentile(first_token, 0.95),
        "completion_p95_ms": _percentile(completion, 0.95),
        "disconnect_count": sum(1 for record in stream_records if record.disconnected),
    }

    summary = {
        "overall": {
            "requests": total,
            "error_rate": (len(errors) / total) if total else 0.0,
            "timeout_rate": (sum(1 for row in records if row.timeout) / total) if total else 0.0,
        },
        "route_class": route_summary,
        "tier": tier_summary,
        "sse": sse_summary,
        "extra": extra or {},
    }
    return summary


def write_report(
    *,
    report_dir: Path,
    scenario: str,
    duration_s: int,
    deterministic: bool,
    summary: dict[str, Any],
    records: list[RequestRecord],
    stream_records: list[StreamRecord],
) -> tuple[Path, Path]:
    # Persist both JSON and markdown artifacts for reproducible diagnostics.
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "scenario": scenario,
        "duration_s": duration_s,
        "deterministic": deterministic,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "records": [asdict(record) for record in records],
        "stream_records": [asdict(record) for record in stream_records],
    }
    json_path = report_dir / f"{scenario}-{timestamp}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    md_lines = [
        f"# Perf Report: {scenario}",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- duration_s: {duration_s}",
        f"- deterministic: {deterministic}",
        "",
        "## Overall",
        "",
        f"- requests: {summary['overall']['requests']}",
        f"- error_rate: {summary['overall']['error_rate']:.4f}",
        f"- timeout_rate: {summary['overall']['timeout_rate']:.4f}",
        "",
        "## Route Class",
        "",
        "| route_class | count | p95_ms | p99_ms | error_rate | shed | degrade |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for route_class, stats in sorted(summary["route_class"].items()):
        md_lines.append(
            "| "
            + " | ".join(
                [
                    route_class,
                    str(stats["count"]),
                    f"{(stats['p95_ms'] or 0):.2f}",
                    f"{(stats['p99_ms'] or 0):.2f}",
                    f"{stats['error_rate']:.4f}",
                    str(stats["shed_count"]),
                    str(stats["degrade_count"]),
                ]
            )
            + " |"
        )
    md_lines.extend(
        [
            "",
            "## SSE",
            "",
            f"- first_token_p95_ms: {summary['sse']['first_token_p95_ms']}",
            f"- completion_p95_ms: {summary['sse']['completion_p95_ms']}",
            f"- disconnect_count: {summary['sse']['disconnect_count']}",
        ]
    )
    md_path = report_dir / f"{scenario}-{timestamp}.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return json_path, md_path
