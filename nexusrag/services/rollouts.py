from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from nexusrag.core.config import get_settings
from nexusrag.services.resilience import get_resilience_redis


logger = logging.getLogger(__name__)

KILL_SWITCH_KEYS = {
    "kill.run": "kill_run",
    "kill.ingest": "kill_ingest",
    "kill.tts": "kill_tts",
    "kill.external_retrieval": "kill_external_retrieval",
}

CANARY_KEYS = {
    "rollout.tts": "rollout_tts_pct",
    "rollout.external_retrieval": "rollout_external_retrieval_pct",
}


@dataclass(frozen=True)
class RolloutState:
    # Snapshot rollout configuration for admin responses.
    kill_switches: dict[str, bool]
    canary_percentages: dict[str, int]


def _kill_key(name: str) -> str:
    settings = get_settings()
    return f\"{settings.rollout_redis_prefix}:kill:{name}\"


def _canary_key(name: str) -> str:
    settings = get_settings()
    return f\"{settings.rollout_redis_prefix}:canary:{name}\"


async def _get_bool(key: str, default: bool) -> bool:
    redis = await get_resilience_redis()
    if redis is None:
        return default
    try:
        raw = await redis.get(key)
    except Exception as exc:  # noqa: BLE001 - fail open to env defaults
        logger.warning(\"rollout_redis_read_failed key=%s\", key, exc_info=exc)
        return default
    if raw is None:
        return default
    return str(raw).lower() in {\"1\", \"true\", \"yes\", \"on\"}


async def _get_int(key: str, default: int) -> int:
    redis = await get_resilience_redis()
    if redis is None:
        return default
    try:
        raw = await redis.get(key)
    except Exception as exc:  # noqa: BLE001 - fall back to env defaults
        logger.warning(\"rollout_redis_read_failed key=%s\", key, exc_info=exc)
        return default
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


async def get_kill_switches() -> dict[str, bool]:
    settings = get_settings()
    results: dict[str, bool] = {}
    for name, attr in KILL_SWITCH_KEYS.items():
        default = bool(getattr(settings, attr))
        results[name] = await _get_bool(_kill_key(name), default)
    return results


async def set_kill_switches(updates: dict[str, bool]) -> dict[str, bool]:
    redis = await get_resilience_redis()
    if redis is None:
        return updates
    for name, enabled in updates.items():
        await redis.set(_kill_key(name), "true" if enabled else "false")
    return updates


async def get_canary_percentages() -> dict[str, int]:
    settings = get_settings()
    results: dict[str, int] = {}
    for name, attr in CANARY_KEYS.items():
        default = int(getattr(settings, attr))
        results[name] = await _get_int(_canary_key(name), default)
    return results


async def set_canary_percentages(updates: dict[str, int]) -> dict[str, int]:
    redis = await get_resilience_redis()
    if redis is None:
        return updates
    for name, percentage in updates.items():
        await redis.set(_canary_key(name), str(int(percentage)))
    return updates


async def get_rollout_state() -> RolloutState:
    # Fetch kill switch + canary settings for ops visibility.
    kill_switches = await get_kill_switches()
    canary_percentages = await get_canary_percentages()
    return RolloutState(kill_switches=kill_switches, canary_percentages=canary_percentages)


async def resolve_kill_switch(name: str) -> bool:
    # Resolve kill switches with Redis override, fallback to env defaults.
    settings = get_settings()
    attr = KILL_SWITCH_KEYS[name]
    default = bool(getattr(settings, attr))
    return await _get_bool(_kill_key(name), default)


async def resolve_canary_percentage(name: str) -> int:
    settings = get_settings()
    attr = CANARY_KEYS[name]
    default = int(getattr(settings, attr))
    return await _get_int(_canary_key(name), default)
