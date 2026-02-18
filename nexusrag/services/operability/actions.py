from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import OperatorAction
from nexusrag.services.audit import record_event
from nexusrag.services.failover import set_write_freeze
from nexusrag.services.resilience import get_resilience_redis, reset_circuit_breaker


_FORCED_SHED_PREFIX = "nexusrag:ops:forced_shed:v2"
_FORCED_TTS_PREFIX = "nexusrag:ops:forced_tts_disabled:v2"


def _utc_now() -> datetime:
    # Keep operator action timestamps timezone-safe for timeline ordering.
    return datetime.now(timezone.utc)


def _forced_shed_key(tenant_id: str, route_class: str) -> str:
    return f"{_FORCED_SHED_PREFIX}:{tenant_id}:{route_class}"


def _forced_tts_key(tenant_id: str) -> str:
    return f"{_FORCED_TTS_PREFIX}:{tenant_id}"


def _allowed_writer_region() -> bool:
    # Restrict forced-flag writers to primary region unless assisted failover mode explicitly permits it.
    settings = get_settings()
    if settings.region_role.strip().lower() == "primary":
        return True
    return settings.failover_enabled and settings.failover_mode.strip().lower() == "assisted"


async def _set_versioned_flag(*, key: str, value: bool, ttl_s: int) -> dict[str, Any]:
    # Encode forced-control flags with version + region metadata so cross-region writes are auditable and bounded.
    redis = await get_resilience_redis()
    if redis is None:
        return {"applied": False, "reason": "redis_unavailable"}
    if not _allowed_writer_region():
        return {"applied": False, "reason": "region_not_allowed"}

    version_key = f"{key}:version"
    version = int(await redis.incr(version_key))
    payload = {
        "value": bool(value),
        "version": version,
        "set_by_region": get_settings().region_id,
        "set_at": _utc_now().isoformat(),
        "ttl_s": max(1, int(ttl_s)),
    }
    await redis.set(key, json.dumps(payload), ex=max(1, int(ttl_s)))
    return {"applied": True, "flag": payload}


def _decode_flag_payload(raw_value: str) -> bool:
    # Parse structured forced-control payloads and fail safe to disabled on malformed values.
    try:
        decoded = json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value == "1"
    if isinstance(decoded, dict):
        return bool(decoded.get("value"))
    return False


async def set_forced_shed(*, tenant_id: str, route_class: str, enabled: bool, ttl_s: int | None = None) -> dict[str, Any]:
    # Apply forced shed as a TTL-bounded versioned flag to prevent stale control-plane states.
    ttl = int(ttl_s or get_settings().ops_forced_flag_ttl_s)
    return await _set_versioned_flag(key=_forced_shed_key(tenant_id, route_class), value=enabled, ttl_s=ttl)


async def get_forced_shed(*, tenant_id: str, route_class: str) -> bool:
    # Resolve forced-shed state and fail open (disabled) when Redis is unavailable.
    redis = await get_resilience_redis()
    if redis is None:
        return False
    value = await redis.get(_forced_shed_key(tenant_id, route_class))
    if not value:
        return False
    raw = value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)
    return _decode_flag_payload(raw)


async def set_forced_tts_disabled(*, tenant_id: str, disabled: bool, ttl_s: int | None = None) -> dict[str, Any]:
    # Apply forced TTS disable as a bounded flag so emergency controls expire without manual cleanup.
    ttl = int(ttl_s or get_settings().ops_forced_flag_ttl_s)
    return await _set_versioned_flag(key=_forced_tts_key(tenant_id), value=disabled, ttl_s=ttl)


async def get_forced_tts_disabled(*, tenant_id: str) -> bool:
    # Resolve forced TTS disablement and default to false when Redis is unavailable.
    redis = await get_resilience_redis()
    if redis is None:
        return False
    value = await redis.get(_forced_tts_key(tenant_id))
    if not value:
        return False
    raw = value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)
    return _decode_flag_payload(raw)


async def apply_operator_action(
    *,
    session: AsyncSession,
    tenant_id: str,
    action_type: str,
    idempotency_key: str,
    requested_by: str,
    actor_role: str | None,
    request_id: str | None,
    params: dict[str, Any] | None = None,
) -> OperatorAction:
    # Deduplicate operator actions at write time so retries remain side-effect free.
    existing = (
        await session.execute(
            select(OperatorAction).where(
                OperatorAction.tenant_id == tenant_id,
                OperatorAction.requested_by == requested_by,
                OperatorAction.action_type == action_type,
                OperatorAction.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    action = OperatorAction(
        id=uuid4().hex,
        tenant_id=tenant_id,
        action_type=action_type,
        idempotency_key=idempotency_key,
        requested_by=requested_by,
        status="running",
        request_json=params or {},
        result_json=None,
        requested_at=_utc_now(),
    )
    session.add(action)
    await session.flush()
    try:
        result_json: dict[str, Any] | None
        if action_type == "freeze_writes":
            result_json = await set_write_freeze(
                session=session,
                freeze=bool((params or {}).get("freeze", True)),
                reason=(params or {}).get("reason"),
                actor_id=requested_by,
                actor_role=actor_role,
                tenant_id=tenant_id,
                request_id=request_id,
            )
        elif action_type == "enable_shed":
            route_class = str((params or {}).get("route_class") or "run")
            flag_result = await set_forced_shed(tenant_id=tenant_id, route_class=route_class, enabled=True)
            result_json = {"tenant_id": tenant_id, "route_class": route_class, "enabled": bool(flag_result.get("applied")), **flag_result}
        elif action_type == "disable_tts":
            flag_result = await set_forced_tts_disabled(tenant_id=tenant_id, disabled=True)
            result_json = {"tenant_id": tenant_id, "disabled": bool(flag_result.get("applied")), **flag_result}
        elif action_type == "reset_breaker":
            breaker_name = str((params or {}).get("integration") or "")
            await reset_circuit_breaker(breaker_name)
            result_json = {"integration": breaker_name, "state": "closed"}
        else:
            raise ValueError("unsupported_action")

        action.status = "completed"
        action.result_json = result_json
        action.completed_at = _utc_now()
        await session.commit()
        await session.refresh(action)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=requested_by,
            actor_role=actor_role,
            event_type=f"ops.action.{action_type}",
            outcome="success",
            resource_type="operator_action",
            resource_id=action.id,
            request_id=request_id,
            metadata={"params": params or {}},
            commit=True,
            best_effort=True,
        )
        return action
    except Exception as exc:  # noqa: BLE001 - surface controlled error payloads while preserving action trace.
        await session.rollback()
        # Persist failure rows in a fresh transaction so operators can inspect failed attempts.
        failed = OperatorAction(
            id=uuid4().hex,
            tenant_id=tenant_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            requested_by=requested_by,
            status="failed",
            request_json=params or {},
            result_json=None,
            error_code="ACTION_FAILED",
            requested_at=_utc_now(),
            completed_at=_utc_now(),
        )
        session.add(failed)
        await session.commit()
        await session.refresh(failed)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=requested_by,
            actor_role=actor_role,
            event_type=f"ops.action.{action_type}",
            outcome="failure",
            resource_type="operator_action",
            resource_id=failed.id,
            request_id=request_id,
            metadata={"params": params or {}, "error": str(exc)},
            error_code="ACTION_FAILED",
            commit=True,
            best_effort=True,
        )
        return failed
