from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexusrag.core.config import get_settings


VALID_ROUTE_CLASSES = {"run", "read", "mutation", "ingest", "ops", "admin"}
VALID_ENFORCEMENT_MODES = {"observe", "warn", "enforce"}


class SlaPolicyValidationError(ValueError):
    # Raise typed validation errors so API handlers can map to stable error codes.
    pass


@dataclass(frozen=True)
class SlaObjectives:
    availability_min_pct: float
    p95_ms_max: dict[str, float]
    p99_ms_max: dict[str, float]
    max_error_budget_burn_5m: float
    saturation_max_pct: float


@dataclass(frozen=True)
class SlaEnforcement:
    mode: str
    breach_window_minutes: int
    consecutive_windows_to_trigger: int


@dataclass(frozen=True)
class SlaMitigation:
    allow_degrade: bool
    disable_tts_first: bool
    reduce_top_k_floor: int
    cap_output_tokens: int
    provider_fallback_order: tuple[str, ...]


@dataclass(frozen=True)
class SlaAutoscalingLink:
    profile_id: str | None
    inline_policy: dict[str, Any] | None


@dataclass(frozen=True)
class SlaPolicyConfig:
    objectives: SlaObjectives
    enforcement: SlaEnforcement
    mitigation: SlaMitigation
    autoscaling_link: SlaAutoscalingLink


def _as_dict(value: Any, *, field: str) -> dict[str, Any]:
    # Enforce object payloads for policy sections to avoid ambiguous parsing.
    if not isinstance(value, dict):
        raise SlaPolicyValidationError(f"{field} must be an object")
    return value


def _as_float(value: Any, *, field: str, min_value: float | None = None, max_value: float | None = None) -> float:
    # Coerce numeric fields and enforce configured bounds.
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SlaPolicyValidationError(f"{field} must be numeric") from exc
    if min_value is not None and parsed < min_value:
        raise SlaPolicyValidationError(f"{field} must be >= {min_value}")
    if max_value is not None and parsed > max_value:
        raise SlaPolicyValidationError(f"{field} must be <= {max_value}")
    return parsed


def _as_int(value: Any, *, field: str, min_value: int | None = None, max_value: int | None = None) -> int:
    # Coerce integer fields and enforce configured bounds.
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SlaPolicyValidationError(f"{field} must be an integer") from exc
    if min_value is not None and parsed < min_value:
        raise SlaPolicyValidationError(f"{field} must be >= {min_value}")
    if max_value is not None and parsed > max_value:
        raise SlaPolicyValidationError(f"{field} must be <= {max_value}")
    return parsed


def _parse_latency_map(raw: Any, *, field: str, required: bool = True) -> dict[str, float]:
    # Validate route-class keyed latency thresholds.
    if raw is None and not required:
        return {}
    mapping = _as_dict(raw, field=field)
    parsed: dict[str, float] = {}
    for route_class, value in mapping.items():
        route = str(route_class)
        if route not in VALID_ROUTE_CLASSES:
            raise SlaPolicyValidationError(f"{field}.{route} route_class is invalid")
        parsed[route] = _as_float(value, field=f"{field}.{route}", min_value=1)
    if required and not parsed:
        raise SlaPolicyValidationError(f"{field} must include at least one route_class threshold")
    return parsed


def parse_policy_config(raw: dict[str, Any] | None) -> SlaPolicyConfig:
    # Parse and validate policy JSON into a canonical in-memory shape.
    settings = get_settings()
    payload = raw or {}
    if not isinstance(payload, dict):
        raise SlaPolicyValidationError("config_json must be an object")

    objectives_raw = _as_dict(payload.get("objectives"), field="objectives")
    enforcement_raw = _as_dict(payload.get("enforcement"), field="enforcement")
    mitigation_raw = _as_dict(payload.get("mitigation"), field="mitigation")
    autoscaling_raw = payload.get("autoscaling_link") or {}
    if not isinstance(autoscaling_raw, dict):
        raise SlaPolicyValidationError("autoscaling_link must be an object")

    objectives = SlaObjectives(
        availability_min_pct=_as_float(
            objectives_raw.get("availability_min_pct"),
            field="objectives.availability_min_pct",
            min_value=0,
            max_value=100,
        ),
        p95_ms_max=_parse_latency_map(objectives_raw.get("p95_ms_max"), field="objectives.p95_ms_max"),
        p99_ms_max=_parse_latency_map(
            objectives_raw.get("p99_ms_max"),
            field="objectives.p99_ms_max",
            required=False,
        ),
        max_error_budget_burn_5m=_as_float(
            objectives_raw.get("max_error_budget_burn_5m"),
            field="objectives.max_error_budget_burn_5m",
            min_value=0,
        ),
        saturation_max_pct=_as_float(
            objectives_raw.get("saturation_max_pct", 95),
            field="objectives.saturation_max_pct",
            min_value=0,
            max_value=100,
        ),
    )

    mode = str(enforcement_raw.get("mode", settings.sla_default_enforcement_mode))
    if mode not in VALID_ENFORCEMENT_MODES:
        raise SlaPolicyValidationError("enforcement.mode is invalid")
    enforcement = SlaEnforcement(
        mode=mode,
        breach_window_minutes=_as_int(
            enforcement_raw.get("breach_window_minutes", 5),
            field="enforcement.breach_window_minutes",
            min_value=1,
            max_value=120,
        ),
        consecutive_windows_to_trigger=_as_int(
            enforcement_raw.get("consecutive_windows_to_trigger", settings.sla_default_breach_windows),
            field="enforcement.consecutive_windows_to_trigger",
            min_value=1,
            max_value=20,
        ),
    )

    fallback_order = mitigation_raw.get("provider_fallback_order", [])
    if not isinstance(fallback_order, list):
        raise SlaPolicyValidationError("mitigation.provider_fallback_order must be an array")
    mitigation = SlaMitigation(
        allow_degrade=bool(mitigation_raw.get("allow_degrade", True)),
        disable_tts_first=bool(mitigation_raw.get("disable_tts_first", settings.sla_degrade_tts_disable)),
        reduce_top_k_floor=_as_int(
            mitigation_raw.get("reduce_top_k_floor", settings.sla_degrade_top_k_floor),
            field="mitigation.reduce_top_k_floor",
            min_value=1,
            max_value=50,
        ),
        cap_output_tokens=_as_int(
            mitigation_raw.get("cap_output_tokens", settings.sla_degrade_max_output_tokens),
            field="mitigation.cap_output_tokens",
            min_value=1,
            max_value=4096,
        ),
        provider_fallback_order=tuple(str(item) for item in fallback_order),
    )

    profile_id = autoscaling_raw.get("profile_id")
    if profile_id is not None and not str(profile_id).strip():
        raise SlaPolicyValidationError("autoscaling_link.profile_id must not be empty")
    inline_policy = autoscaling_raw.get("inline_policy")
    if inline_policy is not None and not isinstance(inline_policy, dict):
        raise SlaPolicyValidationError("autoscaling_link.inline_policy must be an object")

    autoscaling_link = SlaAutoscalingLink(
        profile_id=str(profile_id) if profile_id is not None else None,
        inline_policy=inline_policy,
    )
    return SlaPolicyConfig(
        objectives=objectives,
        enforcement=enforcement,
        mitigation=mitigation,
        autoscaling_link=autoscaling_link,
    )
