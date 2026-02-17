from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PerfGateThresholds:
    # Keep perf gates explicit and environment-overridable.
    run_p95_ms_max: float
    max_error_rate: float
    max_ingest_queue_wait_p95_ms: float
    max_memory_growth_mb: float
    min_noisy_neighbor_success_ratio: float


def evaluate_perf_gates(*, aggregate: dict[str, Any], thresholds: PerfGateThresholds) -> list[str]:
    # Return gate violations with actionable messages.
    violations: list[str] = []

    run_stats = (aggregate.get("route_class") or {}).get("run") or {}
    run_p95 = run_stats.get("p95_ms")
    if run_p95 is not None and float(run_p95) > thresholds.run_p95_ms_max:
        violations.append(
            f"run_p95_ms_exceeded actual={float(run_p95):.2f} threshold={thresholds.run_p95_ms_max:.2f}"
        )

    overall_error_rate = float((aggregate.get("overall") or {}).get("error_rate") or 0.0)
    if overall_error_rate > thresholds.max_error_rate:
        violations.append(
            f"error_rate_exceeded actual={overall_error_rate:.4f} threshold={thresholds.max_error_rate:.4f}"
        )

    ingest_wait = float(((aggregate.get("extra") or {}).get("ingest_queue_wait_p95_ms") or 0.0))
    if ingest_wait > thresholds.max_ingest_queue_wait_p95_ms:
        violations.append(
            f"ingest_queue_wait_p95_exceeded actual={ingest_wait:.2f} threshold={thresholds.max_ingest_queue_wait_p95_ms:.2f}"
        )

    memory_growth_mb = float(((aggregate.get("extra") or {}).get("memory_growth_mb") or 0.0))
    if memory_growth_mb > thresholds.max_memory_growth_mb:
        violations.append(
            f"memory_growth_exceeded actual={memory_growth_mb:.2f} threshold={thresholds.max_memory_growth_mb:.2f}"
        )

    noisy_ratio = float(((aggregate.get("extra") or {}).get("noisy_neighbor_success_ratio") or 1.0))
    if noisy_ratio < thresholds.min_noisy_neighbor_success_ratio:
        violations.append(
            f"noisy_neighbor_starvation actual={noisy_ratio:.4f} threshold={thresholds.min_noisy_neighbor_success_ratio:.4f}"
        )

    return violations
