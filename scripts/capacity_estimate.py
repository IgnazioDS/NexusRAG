from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TierInput:
    # Capture per-tier assumptions for queueing and throughput estimates.
    name: str
    run_p95_ms: float
    ingest_docs_per_min: float
    max_streams: int
    api_replicas: int
    worker_replicas: int


def sustainable_rps(*, concurrency: int, service_time_ms: float, headroom: float) -> float:
    # Little's Law approximation: lambda ~= concurrency / service_time.
    if service_time_ms <= 0:
        return 0.0
    raw = concurrency / (service_time_ms / 1000.0)
    return raw * (1.0 - headroom)


def ingestion_mb_per_min(*, docs_per_min: float, avg_doc_mb: float) -> float:
    # Convert docs/min into MB/min using average document size assumptions.
    return docs_per_min * avg_doc_mb


def build_model(*, headroom: float) -> dict[str, object]:
    # Build tier capacity outputs with explicit formulas and assumptions.
    tiers = [
        TierInput("standard", run_p95_ms=1600.0, ingest_docs_per_min=180.0, max_streams=40, api_replicas=2, worker_replicas=1),
        TierInput("pro", run_p95_ms=1200.0, ingest_docs_per_min=420.0, max_streams=90, api_replicas=4, worker_replicas=2),
        TierInput("enterprise", run_p95_ms=900.0, ingest_docs_per_min=900.0, max_streams=180, api_replicas=8, worker_replicas=4),
    ]

    model_rows = []
    for tier in tiers:
        run_rps = sustainable_rps(concurrency=tier.max_streams, service_time_ms=tier.run_p95_ms, headroom=headroom)
        read_rps = sustainable_rps(concurrency=tier.max_streams * 2, service_time_ms=350.0, headroom=headroom)
        mutation_rps = sustainable_rps(concurrency=max(10, tier.max_streams // 2), service_time_ms=650.0, headroom=headroom)
        ingest_mb = ingestion_mb_per_min(docs_per_min=tier.ingest_docs_per_min, avg_doc_mb=0.08)
        model_rows.append(
            {
                "tier": tier.name,
                "sustainable_rps": {
                    "run": round(run_rps, 2),
                    "read": round(read_rps, 2),
                    "mutation": round(mutation_rps, 2),
                    "ops": round(read_rps * 0.25, 2),
                },
                "latency_ms": {
                    "run_p95": tier.run_p95_ms,
                    "run_p99": round(tier.run_p95_ms * 1.35, 1),
                    "read_p95": 350.0,
                    "mutation_p95": 650.0,
                },
                "max_concurrent_streams": tier.max_streams,
                "ingestion": {
                    "docs_per_min": tier.ingest_docs_per_min,
                    "mb_per_min": round(ingest_mb, 2),
                },
                "replicas": {
                    "api": tier.api_replicas,
                    "worker": tier.worker_replicas,
                },
            }
        )

    return {
        "headroom": headroom,
        "assumptions": {
            "queue_model": "Little's Law: lambda = concurrency / service_time",
            "avg_doc_size_mb": 0.08,
            "redis": "single shard with persistence enabled",
            "postgres": "primary + 1 read replica, pgbouncer optional",
            "scale_policy": "autoscale when p95 > target for 3 consecutive windows; shed after saturation breach",
        },
        "tiers": model_rows,
    }


def render_markdown(model: dict[str, object]) -> str:
    # Render markdown artifact for runbooks and release docs.
    lines = [
        "# Capacity Model",
        "",
        f"Headroom: {float(model['headroom']) * 100:.0f}%",
        "",
        "| tier | run_rps | read_rps | mutation_rps | run_p95_ms | run_p99_ms | max_streams | ingest_docs_min | ingest_mb_min | api_replicas | worker_replicas |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in model["tiers"]:
        sustainable = row["sustainable_rps"]
        latency = row["latency_ms"]
        ingest = row["ingestion"]
        replicas = row["replicas"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["tier"]),
                    f"{sustainable['run']}",
                    f"{sustainable['read']}",
                    f"{sustainable['mutation']}",
                    f"{latency['run_p95']}",
                    f"{latency['run_p99']}",
                    f"{row['max_concurrent_streams']}",
                    f"{ingest['docs_per_min']}",
                    f"{ingest['mb_per_min']}",
                    f"{replicas['api']}",
                    f"{replicas['worker']}",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Assumptions",
            "",
        ]
    )
    for key, value in model["assumptions"].items():
        lines.append(f"- {key}: {value}")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate NexusRAG backend capacity by tenant tier")
    parser.add_argument("--headroom", type=float, default=0.30, help="Fractional safety headroom")
    parser.add_argument("--json-out", type=Path, default=Path("tests/perf/reports/capacity-model.json"))
    parser.add_argument("--md-out", type=Path, default=Path("docs/capacity-model.md"))
    args = parser.parse_args()

    model = build_model(headroom=max(0.0, min(args.headroom, 0.9)))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)

    args.json_out.write_text(json.dumps(model, indent=2, sort_keys=True), encoding="utf-8")
    args.md_out.write_text(render_markdown(model), encoding="utf-8")
    print(args.json_out)
    print(args.md_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
