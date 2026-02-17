from __future__ import annotations

from tests.perf.utils.assertions import PerfGateThresholds, evaluate_perf_gates


def test_perf_gates_pass_when_within_thresholds() -> None:
    aggregate = {
        "overall": {"error_rate": 0.01},
        "route_class": {"run": {"p95_ms": 1200.0}},
        "extra": {
            "ingest_queue_wait_p95_ms": 1800.0,
            "memory_growth_mb": 120.0,
            "noisy_neighbor_success_ratio": 0.9,
        },
    }
    thresholds = PerfGateThresholds(
        run_p95_ms_max=1800.0,
        max_error_rate=0.02,
        max_ingest_queue_wait_p95_ms=2500.0,
        max_memory_growth_mb=256.0,
        min_noisy_neighbor_success_ratio=0.75,
    )
    assert evaluate_perf_gates(aggregate=aggregate, thresholds=thresholds) == []


def test_perf_gates_detect_multiple_violations() -> None:
    aggregate = {
        "overall": {"error_rate": 0.08},
        "route_class": {"run": {"p95_ms": 2600.0}},
        "extra": {
            "ingest_queue_wait_p95_ms": 6000.0,
            "memory_growth_mb": 512.0,
            "noisy_neighbor_success_ratio": 0.40,
        },
    }
    thresholds = PerfGateThresholds(
        run_p95_ms_max=1800.0,
        max_error_rate=0.02,
        max_ingest_queue_wait_p95_ms=2500.0,
        max_memory_growth_mb=256.0,
        min_noisy_neighbor_success_ratio=0.75,
    )
    violations = evaluate_perf_gates(aggregate=aggregate, thresholds=thresholds)
    assert any(item.startswith("run_p95_ms_exceeded") for item in violations)
    assert any(item.startswith("error_rate_exceeded") for item in violations)
    assert any(item.startswith("ingest_queue_wait_p95_exceeded") for item in violations)
    assert any(item.startswith("memory_growth_exceeded") for item in violations)
    assert any(item.startswith("noisy_neighbor_starvation") for item in violations)
