from __future__ import annotations

from datetime import date

from nexusrag.services.usage_dashboard import aggregate_request_counts, build_timeseries_points


def test_aggregate_request_counts_groups_by_route_class() -> None:
    metadata = [
        {"path": "/run", "method": "POST"},
        {"path": "/documents", "method": "GET"},
        {"path": "/documents", "method": "POST"},
        {"path": "/ops/health", "method": "GET"},
    ]

    counts = aggregate_request_counts(metadata)
    assert counts.total == 4
    assert counts.by_route_class["run"] == 1
    assert counts.by_route_class["read"] == 1
    assert counts.by_route_class["mutation"] == 1
    assert counts.by_route_class["ops"] == 1


def test_build_timeseries_points_fills_missing_dates() -> None:
    start = date(2026, 2, 1)
    counts = {date(2026, 2, 1): 3, date(2026, 2, 3): 1}
    points = build_timeseries_points(start_date=start, days=3, counts_by_date=counts)

    assert points == [
        {"ts": "2026-02-01", "value": 3},
        {"ts": "2026-02-02", "value": 0},
        {"ts": "2026-02-03", "value": 1},
    ]
