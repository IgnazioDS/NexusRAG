from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import json
from typing import Any


@dataclass(frozen=True)
class PolicyInvalidError(ValueError):
    # Surface invalid policy conditions with stable error handling.
    message: str


@dataclass(frozen=True)
class PolicyTooComplexError(ValueError):
    # Block overly complex policies to keep evaluation deterministic.
    message: str


_ALLOWED_OPERATORS = {
    "all",
    "any",
    "not",
    "eq",
    "ne",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "starts_with",
    "time_between",
    "date_between",
}


def policy_size_bytes(value: Any) -> int:
    # Measure serialized condition size for policy complexity enforcement.
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def validate_condition(condition: Any, *, max_depth: int) -> None:
    # Enforce depth and operator constraints before evaluation.
    if condition == {}:
        return
    depth = _condition_depth(condition)
    if depth > max_depth:
        raise PolicyTooComplexError(f"Policy depth {depth} exceeds max {max_depth}")
    _validate_structure(condition)


def evaluate_condition(condition: Any, context: dict[str, Any]) -> bool:
    # Evaluate a deterministic condition DSL using the provided context.
    if condition is None:
        return True
    if isinstance(condition, bool):
        return condition
    if condition == {}:
        return True
    if not isinstance(condition, dict):
        raise PolicyInvalidError("Condition must be an object")
    if len(condition) != 1:
        raise PolicyInvalidError("Condition must include a single operator")
    operator, payload = next(iter(condition.items()))
    if operator not in _ALLOWED_OPERATORS:
        raise PolicyInvalidError(f"Unsupported operator: {operator}")

    if operator == "all":
        items = _ensure_list(payload, operator)
        return all(evaluate_condition(item, context) for item in items)
    if operator == "any":
        items = _ensure_list(payload, operator)
        return any(evaluate_condition(item, context) for item in items)
    if operator == "not":
        return not evaluate_condition(payload, context)

    left, right = _resolve_operands(payload, context)
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "in":
        return _in_operator(left, right)
    if operator == "not_in":
        return not _in_operator(left, right)
    if operator == "gt":
        return _compare(left, right, op="gt")
    if operator == "gte":
        return _compare(left, right, op="gte")
    if operator == "lt":
        return _compare(left, right, op="lt")
    if operator == "lte":
        return _compare(left, right, op="lte")
    if operator == "contains":
        return _contains(left, right)
    if operator == "starts_with":
        return _starts_with(left, right)
    if operator == "time_between":
        return _time_between(left, right)
    if operator == "date_between":
        return _date_between(left, right)

    raise PolicyInvalidError(f"Unhandled operator: {operator}")


def _validate_structure(condition: Any) -> None:
    # Ensure the condition uses supported operators and shapes.
    if condition is None or isinstance(condition, bool):
        return
    if not isinstance(condition, dict):
        raise PolicyInvalidError("Condition must be an object")
    if len(condition) != 1:
        raise PolicyInvalidError("Condition must include a single operator")
    operator, payload = next(iter(condition.items()))
    if operator not in _ALLOWED_OPERATORS:
        raise PolicyInvalidError(f"Unsupported operator: {operator}")
    if operator in {"all", "any"}:
        items = _ensure_list(payload, operator)
        for item in items:
            _validate_structure(item)
        return
    if operator == "not":
        _validate_structure(payload)
        return


def _condition_depth(condition: Any, depth: int = 1) -> int:
    # Compute condition depth for complexity enforcement.
    if condition is None or isinstance(condition, bool):
        return depth
    if not isinstance(condition, dict) or len(condition) != 1:
        return depth
    operator, payload = next(iter(condition.items()))
    if operator in {"all", "any"}:
        items = payload if isinstance(payload, list) else []
        if not items:
            return depth + 1
        return max(_condition_depth(item, depth + 1) for item in items)
    if operator == "not":
        return _condition_depth(payload, depth + 1)
    return depth + 1


def _ensure_list(payload: Any, operator: str) -> list[Any]:
    # Normalize logical operands to lists to keep evaluation simple.
    if not isinstance(payload, list):
        raise PolicyInvalidError(f"{operator} expects a list")
    return payload


def _resolve_operands(payload: Any, context: dict[str, Any]) -> tuple[Any, Any]:
    # Resolve operands for comparator operators.
    if isinstance(payload, list) and len(payload) == 2:
        left = _resolve_operand(payload[0], context)
        right = _resolve_operand(payload[1], context)
        return left, right
    if isinstance(payload, dict) and "field" in payload:
        left = _resolve_operand({"var": payload.get("field")}, context)
        right = _resolve_operand(payload.get("value"), context)
        return left, right
    if isinstance(payload, dict) and "left" in payload:
        left = _resolve_operand(payload.get("left"), context)
        right = _resolve_operand(payload.get("right"), context)
        return left, right
    raise PolicyInvalidError("Comparator payload must be list or object with field/value")


def _resolve_operand(value: Any, context: dict[str, Any]) -> Any:
    # Resolve variable references into concrete context values.
    if isinstance(value, dict) and "var" in value:
        return _resolve_path(context, str(value.get("var")))
    return value


def _resolve_path(context: dict[str, Any], path: str) -> Any:
    # Resolve dotted paths into context dictionary values.
    if not path:
        return None
    node: Any = context
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def _in_operator(left: Any, right: Any) -> bool:
    # Support membership checks against lists/sets/tuples.
    if right is None:
        return False
    if isinstance(right, (list, tuple, set)):
        return left in right
    return left == right


def _compare(left: Any, right: Any, *, op: str) -> bool:
    # Provide safe comparison for ordered values.
    if left is None or right is None:
        return False
    try:
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
    except TypeError:
        return False
    return False


def _contains(left: Any, right: Any) -> bool:
    # Support substring and list membership checks.
    if left is None:
        return False
    if isinstance(left, str):
        return str(right) in left
    if isinstance(left, (list, set, tuple)):
        return right in left
    return False


def _starts_with(left: Any, right: Any) -> bool:
    # Enforce prefix matches on strings.
    if not isinstance(left, str) or right is None:
        return False
    return left.startswith(str(right))


def _time_between(left: Any, right: Any) -> bool:
    # Check if a time-of-day falls within a start/end window.
    if not isinstance(right, dict):
        raise PolicyInvalidError("time_between expects an object with start/end")
    start_raw = right.get("start")
    end_raw = right.get("end")
    start = _parse_time(start_raw)
    end = _parse_time(end_raw)
    value = _parse_time(left)
    if value is None or start is None or end is None:
        return False
    if start <= end:
        return start <= value <= end
    # Overnight window support (e.g., 22:00-06:00).
    return value >= start or value <= end


def _date_between(left: Any, right: Any) -> bool:
    # Check if a date/datetime falls within a window.
    if not isinstance(right, dict):
        raise PolicyInvalidError("date_between expects an object with start/end")
    start = _parse_datetime(right.get("start"))
    end = _parse_datetime(right.get("end"))
    value = _parse_datetime(left)
    if value is None or start is None or end is None:
        return False
    return start <= value <= end


def _parse_time(value: Any) -> time | None:
    # Parse time-of-day values from strings/datetimes.
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, date) and not isinstance(value, datetime):
        return time(0, 0, 0)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.time()
        except ValueError:
            pass
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
    return None


def _parse_datetime(value: Any) -> datetime | None:
    # Parse datetime values from strings and pass through existing datetimes.
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
