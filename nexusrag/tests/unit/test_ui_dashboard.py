from __future__ import annotations

from nexusrag.services.ui_dashboard import build_dashboard_alerts, build_dashboard_cards


def test_build_dashboard_cards() -> None:
    cards = build_dashboard_cards(
        request_total=10,
        day_quota_used=5,
        month_quota_used=20,
        rate_limit_count=2,
    )
    assert cards[0]["id"] == "requests"
    assert cards[0]["value"] == "10"


def test_build_dashboard_alerts() -> None:
    alerts = build_dashboard_alerts(
        soft_cap_reached=True,
        rate_limit_count=1,
        highlight_messages=["event a", "event b"],
    )
    ids = {alert["id"] for alert in alerts}
    assert "quota-soft-cap" in ids
    assert "rate-limit" in ids
