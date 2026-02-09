from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from nexusrag.apps.api.rate_limit import (
    ROUTE_CLASS_MUTATION,
    ROUTE_CLASS_OPS,
    ROUTE_CLASS_READ,
    ROUTE_CLASS_RUN,
    route_class_for_path,
)


@dataclass(frozen=True)
class RouteClassCounts:
    # Aggregate request counts across route classes for usage dashboards.
    total: int
    by_route_class: dict[str, int]


def aggregate_request_counts(metadata_rows: Iterable[dict[str, Any]]) -> RouteClassCounts:
    # Group auth success events by route class using request metadata.
    by_route_class = {
        ROUTE_CLASS_RUN: 0,
        ROUTE_CLASS_READ: 0,
        ROUTE_CLASS_MUTATION: 0,
        ROUTE_CLASS_OPS: 0,
    }
    total = 0
    for metadata in metadata_rows:
        if not isinstance(metadata, dict):
            continue
        path = metadata.get("path")
        method = metadata.get("method")
        if not path or not method:
            continue
        route_class, _ = route_class_for_path(str(path), str(method))
        by_route_class[route_class] = by_route_class.get(route_class, 0) + 1
        total += 1
    return RouteClassCounts(total=total, by_route_class=by_route_class)


def build_timeseries_points(
    *,
    start_date: date,
    days: int,
    counts_by_date: dict[date, int],
) -> list[dict[str, Any]]:
    # Fill missing dates so chart consumers receive contiguous series points.
    points: list[dict[str, Any]] = []
    for offset in range(days):
        current = start_date + timedelta(days=offset)
        points.append({"ts": current.isoformat(), "value": int(counts_by_date.get(current, 0))})
    return points
