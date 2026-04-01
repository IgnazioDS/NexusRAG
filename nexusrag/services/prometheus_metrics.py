from __future__ import annotations

import time
from collections import defaultdict

from prometheus_client import CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client.metrics_core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
)
from prometheus_client.registry import Collector

from nexusrag.services import telemetry

# Use a private registry so we don't accidentally expose the default
# process-level metrics (CPU, FD count) that prometheus_client adds globally.
_REGISTRY = CollectorRegistry(auto_describe=False)

_WINDOW_S = 60  # Default scrape window for rate/latency metrics.
_LATENCY_BUCKETS = (25, 50, 100, 250, 500, 1000, 2000, 5000, float("inf"))


class _NexusRAGCollector(Collector):
    """Custom Prometheus collector backed by the in-process telemetry module.

    Implements the pull model: ``collect()`` is called only when the /metrics
    endpoint is scraped, so there is no background overhead.
    """

    def describe(self) -> list:
        # Return empty to avoid duplicate-registration errors on hot reload.
        return []

    def collect(self):  # type: ignore[override]
        now = time.time()
        cutoff = now - _WINDOW_S

        # ── Request counters ──────────────────────────────────────────────────
        request_total = CounterMetricFamily(
            "nexusrag_requests_total",
            "Total HTTP requests handled, by route class and status family.",
            labels=["route_class", "status_family"],
        )
        by_class: dict[tuple[str, str], int] = defaultdict(int)
        for s in telemetry._request_samples:
            if s.ts < cutoff:
                continue
            fam = f"{s.status_code // 100}xx"
            by_class[(s.route_class, fam)] += 1
        for (rc, fam), count in by_class.items():
            request_total.add_metric([rc, fam], count)
        yield request_total

        # ── Latency histograms ────────────────────────────────────────────────
        latency_hist = HistogramMetricFamily(
            "nexusrag_request_latency_ms",
            "HTTP request latency in milliseconds, by route class.",
            labels=["route_class"],
        )
        by_rc: dict[str, list[float]] = defaultdict(list)
        for s in telemetry._request_samples:
            if s.ts < cutoff:
                continue
            by_rc[s.route_class].append(s.latency_ms)
        for rc, latencies in by_rc.items():
            buckets: list[tuple[float, int]] = []
            cumulative = 0
            for bound in _LATENCY_BUCKETS:
                cumulative += sum(1 for v in latencies if v <= bound)
                buckets.append((bound, cumulative))
            total_sum = sum(latencies)
            latency_hist.add_metric([rc], buckets=buckets, sum_value=total_sum)
        yield latency_hist

        # ── Rate-limited requests ─────────────────────────────────────────────
        rl_total = CounterMetricFamily(
            "nexusrag_rate_limited_total",
            "Total requests rejected by the rate limiter.",
        )
        rl_count = sum(
            1 for s in telemetry._request_samples
            if s.ts >= cutoff and s.status_code == 429
        )
        rl_total.add_metric([], rl_count)
        yield rl_total

        # ── 5xx error rate ────────────────────────────────────────────────────
        error_total = CounterMetricFamily(
            "nexusrag_server_errors_total",
            "Total 5xx responses in the scrape window.",
        )
        error_count = sum(
            1 for s in telemetry._request_samples
            if s.ts >= cutoff and s.status_code >= 500
        )
        error_total.add_metric([], error_count)
        yield error_total

        # ── Named counters from increment_counter() ───────────────────────────
        for name, value in telemetry.counters_snapshot().items():
            safe_name = name.replace(".", "_").replace("-", "_")
            c = CounterMetricFamily(
                f"nexusrag_{safe_name}",
                f"Internal counter: {name}",
            )
            c.add_metric([], float(value))
            yield c

        # ── Named gauges from set_gauge() ─────────────────────────────────────
        for name, value in telemetry.gauges_snapshot().items():
            safe_name = name.replace(".", "_").replace("-", "_")
            g = GaugeMetricFamily(
                f"nexusrag_{safe_name}",
                f"Internal gauge: {name}",
            )
            g.add_metric([], value)
            yield g

        # ── External call p95 latency ─────────────────────────────────────────
        ext_p95 = GaugeMetricFamily(
            "nexusrag_external_call_p95_latency_ms",
            "P95 latency (ms) for external integration calls in the last 60s.",
            labels=["integration"],
        )
        for integration, stats in telemetry.external_latency_by_integration(_WINDOW_S).items():
            if stats.get("p95") is not None:
                ext_p95.add_metric([integration], stats["p95"])
        yield ext_p95


_REGISTRY.register(_NexusRAGCollector())


def generate_metrics() -> tuple[bytes, str]:
    """Return (body, content_type) suitable for a Prometheus scrape response."""
    return generate_latest(_REGISTRY), CONTENT_TYPE_LATEST
