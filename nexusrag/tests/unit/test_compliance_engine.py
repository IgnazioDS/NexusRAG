from __future__ import annotations

from nexusrag.services.compliance.control_engine import _evaluate_condition


def test_condition_all_any() -> None:
    data = {"status": "healthy", "value": 10}
    condition = {
        "all": [
            {"value_path": "status", "operator": "eq", "threshold": "healthy"},
            {"value_path": "value", "operator": "gte", "threshold": 5},
        ]
    }
    passed, _ = _evaluate_condition(condition, data, 60)
    assert passed is True


def test_condition_any() -> None:
    data = {"status": "degraded", "value": 2}
    condition = {
        "any": [
            {"value_path": "status", "operator": "eq", "threshold": "healthy"},
            {"value_path": "value", "operator": "lte", "threshold": 2},
        ]
    }
    passed, _ = _evaluate_condition(condition, data, 60)
    assert passed is True


def test_condition_aggregation_count() -> None:
    data = {"count": 4}
    condition = {"aggregation": "count", "operator": "lte", "threshold": 10}
    passed, detail = _evaluate_condition(condition, data, 60)
    assert passed is True
    assert detail["value"] == 4


def test_condition_pct_change() -> None:
    data = {"current": 20, "previous": 10}
    condition = {"aggregation": "pct_change", "operator": "gte", "threshold": 50}
    passed, detail = _evaluate_condition(condition, data, 60)
    assert passed is True
    assert detail["value"] >= 50
