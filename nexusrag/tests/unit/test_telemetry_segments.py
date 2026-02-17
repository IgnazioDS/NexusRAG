from __future__ import annotations

from nexusrag.services.telemetry import request_segment_latency_by_class, record_segment_timing


def test_segment_latency_aggregation() -> None:
    # Record segment samples and verify percentile aggregation shape is stable.
    route_class = "perf_test_route"
    segment = "segment_x"
    record_segment_timing(route_class=route_class, segment=segment, latency_ms=100.0)
    record_segment_timing(route_class=route_class, segment=segment, latency_ms=200.0)
    record_segment_timing(route_class=route_class, segment=segment, latency_ms=300.0)
    stats = request_segment_latency_by_class(3600)
    run_stats = stats[route_class][segment]
    assert run_stats["p50"] == 200.0
    assert run_stats["p95"] == 300.0
    assert run_stats["p99"] == 300.0
    assert run_stats["max"] == 300.0
