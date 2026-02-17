from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import math
from statistics import mean
from typing import Deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import SlaMeasurement
from nexusrag.services.ingest.queue import get_queue_depth
from nexusrag.services.telemetry import gauges_snapshot


@dataclass(frozen=True)
class LiveSignals:
    # Provide queue/saturation hints used by SLA and autoscaling evaluators.
    queue_depth: int | None
    saturation_pct: float | None
    signal_quality: str
    details: dict[str, str]


_window_samples: dict[tuple[str, str, int], Deque[tuple[float, float, int, float | None]]] = defaultdict(
    lambda: deque(maxlen=4096)
)


def _utc_now() -> datetime:
    # Use UTC timestamps to keep persisted window boundaries deterministic.
    return datetime.now(timezone.utc)


def _bucket_bounds(now: datetime, window_seconds: int) -> tuple[datetime, datetime]:
    # Align measurement buckets to fixed windows for stable query semantics.
    epoch = int(now.timestamp())
    bucket_end_epoch = (epoch // window_seconds) * window_seconds
    bucket_end = datetime.fromtimestamp(bucket_end_epoch, tz=timezone.utc)
    return bucket_end - timedelta(seconds=window_seconds), bucket_end


def _measurement_id(*, tenant_id: str, route_class: str, window_seconds: int, window_end: datetime) -> str:
    # Generate deterministic ids so repeated writes update the same bucket row.
    raw = f"{tenant_id}:{route_class}:{window_seconds}:{window_end.isoformat()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _percentile(values: list[float], q: float) -> float | None:
    # Compute nearest-rank percentiles deterministically.
    if not values:
        return None
    sorted_values = sorted(values)
    idx = max(0, math.ceil(q * len(sorted_values)) - 1)
    return sorted_values[idx]


def _window_seconds_from_row(row: SlaMeasurement) -> int:
    # Derive the measurement window length from stored timestamps.
    return max(1, int((row.window_end - row.window_start).total_seconds()))


async def record_sla_observation(
    *,
    session: AsyncSession,
    tenant_id: str,
    route_class: str,
    latency_ms: float,
    status_code: int,
    saturation_pct: float | None = None,
    now: datetime | None = None,
) -> list[SlaMeasurement]:
    # Persist 1m/5m rolling measurements from request outcomes and live saturation.
    current = now or _utc_now()
    settings = get_settings()
    windows = sorted({max(60, int(settings.sla_measurement_window_seconds)), 300})
    persisted: list[SlaMeasurement] = []

    for window_seconds in windows:
        key = (tenant_id, route_class, window_seconds)
        sample_queue = _window_samples[key]
        sample_queue.append((current.timestamp(), latency_ms, status_code, saturation_pct))
        cutoff = current.timestamp() - window_seconds
        while sample_queue and sample_queue[0][0] < cutoff:
            sample_queue.popleft()

        latencies = [sample[1] for sample in sample_queue]
        request_count = len(sample_queue)
        error_count = sum(1 for sample in sample_queue if sample[2] >= 500)
        availability_pct = ((request_count - error_count) / request_count * 100.0) if request_count else None
        saturation_values = [sample[3] for sample in sample_queue if sample[3] is not None]
        saturation_avg = mean(saturation_values) if saturation_values else None
        window_start, window_end = _bucket_bounds(current, window_seconds)
        measurement_id = _measurement_id(
            tenant_id=tenant_id,
            route_class=route_class,
            window_seconds=window_seconds,
            window_end=window_end,
        )
        row = await session.get(SlaMeasurement, measurement_id)
        if row is None:
            row = SlaMeasurement(
                id=measurement_id,
                tenant_id=tenant_id,
                route_class=route_class,
                window_start=window_start,
                window_end=window_end,
                request_count=request_count,
                error_count=error_count,
                p50_ms=_percentile(latencies, 0.50),
                p95_ms=_percentile(latencies, 0.95),
                p99_ms=_percentile(latencies, 0.99),
                availability_pct=availability_pct,
                saturation_pct=saturation_avg,
                computed_at=current,
            )
            session.add(row)
        else:
            row.window_start = window_start
            row.window_end = window_end
            row.request_count = request_count
            row.error_count = error_count
            row.p50_ms = _percentile(latencies, 0.50)
            row.p95_ms = _percentile(latencies, 0.95)
            row.p99_ms = _percentile(latencies, 0.99)
            row.availability_pct = availability_pct
            row.saturation_pct = saturation_avg
            row.computed_at = current
        persisted.append(row)
    return persisted


async def load_latest_measurements(
    *,
    session: AsyncSession,
    tenant_id: str,
    route_class: str,
    window_seconds: int,
    limit: int = 5,
) -> list[SlaMeasurement]:
    # Fetch latest measurement rows for a specific tenant/route/window size.
    result = await session.execute(
        select(SlaMeasurement)
        .where(
            SlaMeasurement.tenant_id == tenant_id,
            SlaMeasurement.route_class == route_class,
        )
        .order_by(SlaMeasurement.window_end.desc())
        .limit(max(limit * 8, 16))
    )
    rows = list(result.scalars().all())
    matched = [row for row in rows if _window_seconds_from_row(row) == window_seconds]
    return matched[:limit]


async def latest_measurement(
    *,
    session: AsyncSession,
    tenant_id: str,
    route_class: str,
    window_seconds: int,
) -> SlaMeasurement | None:
    # Return the newest measurement row for policy evaluation.
    rows = await load_latest_measurements(
        session=session,
        tenant_id=tenant_id,
        route_class=route_class,
        window_seconds=window_seconds,
        limit=1,
    )
    return rows[0] if rows else None


def window_seconds_for_label(window_label: str) -> int:
    # Normalize API window labels into integer durations.
    if window_label == "1m":
        return 60
    if window_label == "5m":
        return 300
    raise ValueError("window must be one of: 1m, 5m")


async def collect_live_signals(*, route_class: str) -> LiveSignals:
    # Gather queue/saturation signals while tolerating missing telemetry sources.
    gauges = gauges_snapshot()
    details: dict[str, str] = {}
    queue_depth: int | None = None
    if route_class == "ingest":
        queue_depth = await get_queue_depth()
        if queue_depth is None:
            details["queue_depth"] = "unavailable"
    else:
        gauge_key = f"sla.queue_depth.{route_class}"
        if gauge_key in gauges:
            queue_depth = int(gauges[gauge_key])

    saturation_pct = gauges.get(f"sla.saturation_pct.{route_class}")
    if saturation_pct is None:
        details["saturation_pct"] = "unavailable"
    signal_quality = "ok" if not details else "degraded"
    return LiveSignals(
        queue_depth=queue_depth,
        saturation_pct=float(saturation_pct) if saturation_pct is not None else None,
        signal_quality=signal_quality,
        details=details,
    )
