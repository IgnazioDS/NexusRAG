from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import OperatorAction
from nexusrag.services.audit import record_event
from nexusrag.services.failover import set_write_freeze
from nexusrag.services.resilience import get_resilience_redis, reset_circuit_breaker


_force_flags_local: dict[str, str] = {}
_FORCED_SHED_PREFIX = "nexusrag:ops:forced_shed"
_FORCED_TTS_PREFIX = "nexusrag:ops:forced_tts_disabled"


def _utc_now() -> datetime:
    # Keep operator action timestamps timezone-safe for timeline ordering.
    return datetime.now(timezone.utc)


def _forced_shed_key(tenant_id: str, route_class: str) -> str:
    return f"{_FORCED_SHED_PREFIX}:{tenant_id}:{route_class}"


def _forced_tts_key(tenant_id: str) -> str:
    return f"{_FORCED_TTS_PREFIX}:{tenant_id}"


async def set_forced_shed(*, tenant_id: str, route_class: str, enabled: bool) -> None:
    # Store forced-shed flags in Redis when available, with local fallback for tests.
    redis = await get_resilience_redis()
    key = _forced_shed_key(tenant_id, route_class)
    if redis is None:
        if enabled:
            _force_flags_local[key] = "1"
        else:
            _force_flags_local.pop(key, None)
        return
    if enabled:
        await redis.set(key, "1")
    else:
        await redis.delete(key)


async def get_forced_shed(*, tenant_id: str, route_class: str) -> bool:
    # Resolve forced-shed state without failing closed on Redis outages.
    redis = await get_resilience_redis()
    key = _forced_shed_key(tenant_id, route_class)
    if redis is None:
        return _force_flags_local.get(key) == "1"
    value = await redis.get(key)
    return value == "1"


async def set_forced_tts_disabled(*, tenant_id: str, disabled: bool) -> None:
    # Keep forced TTS disablements tenant-scoped to avoid cross-tenant coupling.
    redis = await get_resilience_redis()
    key = _forced_tts_key(tenant_id)
    if redis is None:
        if disabled:
            _force_flags_local[key] = "1"
        else:
            _force_flags_local.pop(key, None)
        return
    if disabled:
        await redis.set(key, "1")
    else:
        await redis.delete(key)


async def get_forced_tts_disabled(*, tenant_id: str) -> bool:
    # Resolve forced TTS disablement with local fallback in deterministic test mode.
    redis = await get_resilience_redis()
    key = _forced_tts_key(tenant_id)
    if redis is None:
        return _force_flags_local.get(key) == "1"
    value = await redis.get(key)
    return value == "1"


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
            await set_forced_shed(tenant_id=tenant_id, route_class=route_class, enabled=True)
            result_json = {"tenant_id": tenant_id, "route_class": route_class, "enabled": True}
        elif action_type == "disable_tts":
            await set_forced_tts_disabled(tenant_id=tenant_id, disabled=True)
            result_json = {"tenant_id": tenant_id, "disabled": True}
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
