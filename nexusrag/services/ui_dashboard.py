from __future__ import annotations

from typing import Any


def build_dashboard_cards(
    *,
    request_total: int,
    day_quota_used: int,
    month_quota_used: int,
    rate_limit_count: int,
) -> list[dict[str, Any]]:
    # Map raw metrics into UI card descriptors for dashboard rendering.
    return [
        {"id": "requests", "title": "Requests", "value": str(request_total)},
        {"id": "quota_day", "title": "Day quota used", "value": str(day_quota_used)},
        {"id": "quota_month", "title": "Month quota used", "value": str(month_quota_used)},
        {"id": "rate_limits", "title": "Rate limited", "value": str(rate_limit_count)},
    ]


def build_dashboard_alerts(
    *,
    soft_cap_reached: bool,
    rate_limit_count: int,
    highlight_messages: list[str],
) -> list[dict[str, Any]]:
    # Normalize dashboard alerts for quick UI consumption.
    alerts: list[dict[str, Any]] = []
    if soft_cap_reached:
        alerts.append(
            {
                "id": "quota-soft-cap",
                "message": "Quota soft cap reached",
                "severity": "warning",
            }
        )
    if rate_limit_count:
        alerts.append(
            {
                "id": "rate-limit",
                "message": f"{rate_limit_count} requests rate limited",
                "severity": "info",
            }
        )
    for idx, message in enumerate(highlight_messages):
        alerts.append(
            {"id": f"audit-{idx}", "message": message, "severity": "info"}
        )
    return alerts
