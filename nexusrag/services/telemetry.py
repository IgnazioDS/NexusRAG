from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque


@dataclass(frozen=True)
class RequestSample:
    ts: float
    path: str
    route_class: str
    status_code: int
    latency_ms: float


@dataclass(frozen=True)
class ExternalCallSample:
    ts: float
    integration: str
    latency_ms: float
    success: bool


_request_samples: Deque[RequestSample] = deque(maxlen=20000)
_stream_samples: Deque[float] = deque(maxlen=5000)
_external_samples: Deque[ExternalCallSample] = deque(maxlen=10000)
_counters: dict[str, int] = defaultdict(int)


def record_request(*, path: str, route_class: str, status_code: int, latency_ms: float) -> None:
    # Track request latency and status for SLO calculations.
    _request_samples.append(
        RequestSample(
            ts=time.time(),
            path=path,
            route_class=route_class,
            status_code=status_code,
            latency_ms=latency_ms,
        )
    )


def record_stream_duration(duration_ms: float) -> None:
    # Track SSE stream durations for run observability.
    _stream_samples.append(duration_ms)


def record_external_call(*, integration: str, latency_ms: float, success: bool) -> None:
    # Capture external call latency and outcomes.
    _external_samples.append(
        ExternalCallSample(
            ts=time.time(),
            integration=integration,
            latency_ms=latency_ms,
            success=success,
        )
    )


def increment_counter(name: str, value: int = 1) -> None:
    # Store counters for error budgets and ops dashboards.
    _counters[name] += value


def _window_samples(window_s: int) -> list[RequestSample]:
    cutoff = time.time() - window_s
    return [sample for sample in _request_samples if sample.ts >= cutoff]


def availability(window_s: int) -> float | None:
    # Calculate availability as % of non-5xx requests over the window.
    samples = _window_samples(window_s)
    if not samples:
        return None
    total = len(samples)
    failures = sum(1 for sample in samples if sample.status_code >= 500)
    return ((total - failures) / total) * 100.0


def p95_latency(window_s: int, *, path_prefix: str | None = None) -> float | None:
    # Compute p95 latency for requests in the window, optionally filtered by path.
    samples = _window_samples(window_s)
    if path_prefix:
        samples = [sample for sample in samples if sample.path.startswith(path_prefix)]
    if not samples:
        return None
    latencies = sorted(sample.latency_ms for sample in samples)
    idx = max(0, math.ceil(0.95 * len(latencies)) - 1)
    return latencies[idx]


def request_latency_by_class(window_s: int) -> dict[str, dict[str, float | None]]:
    # Aggregate p50/p95/max by route class and status family for ops metrics.
    samples = _window_samples(window_s)
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for sample in samples:
        status_family = f"{sample.status_code // 100}xx"
        grouped[(sample.route_class, status_family)].append(sample.latency_ms)
    result: dict[str, dict[str, float | None]] = {}
    for (route_class, status_family), latencies in grouped.items():
        latencies.sort()
        p50_idx = max(0, math.ceil(0.5 * len(latencies)) - 1)
        p95_idx = max(0, math.ceil(0.95 * len(latencies)) - 1)
        result.setdefault(route_class, {})[status_family] = {
            "p50": latencies[p50_idx],
            "p95": latencies[p95_idx],
            "max": latencies[-1],
        }
    return result


def external_latency_by_integration(window_s: int) -> dict[str, dict[str, float | None]]:
    # Aggregate external call latency for integrations in the window.
    cutoff = time.time() - window_s
    by_integration: dict[str, list[float]] = defaultdict(list)
    for sample in _external_samples:
        if sample.ts < cutoff:
            continue
        by_integration[sample.integration].append(sample.latency_ms)
    result: dict[str, dict[str, float | None]] = {}
    for integration, latencies in by_integration.items():
        latencies.sort()
        p95_idx = max(0, math.ceil(0.95 * len(latencies)) - 1)
        result[integration] = {
            "p95": latencies[p95_idx],
            "max": latencies[-1],
        }
    return result


def stream_duration_stats() -> dict[str, float | None]:
    # Summarize recent SSE stream durations.
    if not _stream_samples:
        return {"p95": None, "max": None}
    latencies = sorted(_stream_samples)
    idx = max(0, math.ceil(0.95 * len(latencies)) - 1)
    return {"p95": latencies[idx], "max": latencies[-1]}


def counters_snapshot() -> dict[str, int]:
    # Return a copy of all counters for metrics reporting.
    return dict(_counters)
