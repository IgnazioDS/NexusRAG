from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import secrets
import time
from typing import Any
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    FailoverClusterState,
    FailoverEvent,
    FailoverToken,
    RegionStatus,
)
from nexusrag.services.audit import record_event
from nexusrag.services.resilience import get_resilience_redis
from nexusrag.services.telemetry import increment_counter, set_gauge


logger = logging.getLogger(__name__)

FAILOVER_STATE_IDLE = "idle"
FAILOVER_STATE_FREEZE_WRITES = "freeze_writes"
FAILOVER_STATE_PRECHECK = "precheck"
FAILOVER_STATE_PROMOTING = "promoting"
FAILOVER_STATE_VERIFICATION = "verification"
FAILOVER_STATE_COMPLETED = "completed"
FAILOVER_STATE_FAILED = "failed"
FAILOVER_STATE_ROLLBACK_PENDING = "rollback_pending"
FAILOVER_STATE_ROLLED_BACK = "rolled_back"

EVENT_STATUS_REQUESTED = "requested"
EVENT_STATUS_VALIDATED = "validated"
EVENT_STATUS_EXECUTING = "executing"
EVENT_STATUS_COMPLETED = "completed"
EVENT_STATUS_FAILED = "failed"
EVENT_STATUS_ROLLED_BACK = "rolled_back"

TOKEN_PURPOSE_PROMOTE = "promote"
TOKEN_PURPOSE_ROLLBACK = "rollback"


@dataclass(frozen=True)
class ReadinessResult:
    # Return a stable readiness shape for ops endpoints and promotion prechecks.
    readiness_score: int
    recommendation: str
    blockers: list[str]
    replication_lag_seconds: int | None
    split_brain_risk: bool
    peer_signals: list[dict[str, Any]]


@dataclass(frozen=True)
class FailoverTokenIssued:
    # Return one-time token payloads; plaintext is never persisted.
    token_id: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class FailoverTransitionResult:
    # Return summarized failover event details to operator APIs.
    event_id: int
    status: str
    from_region: str | None
    to_region: str | None
    epoch: int
    freeze_writes: bool
    blockers: list[str]


def _utc_now() -> datetime:
    # Use UTC timestamps for token expiry and transition timing.
    return datetime.now(timezone.utc)


def _failover_error(code: str, message: str, status_code: int = 409) -> HTTPException:
    # Keep failover errors stable for operator automation.
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _state_transition_allowed(current: str, target: str) -> bool:
    # Enforce an explicit failover state machine to prevent invalid transitions.
    allowed: dict[str, set[str]] = {
        FAILOVER_STATE_IDLE: {FAILOVER_STATE_PRECHECK, FAILOVER_STATE_FREEZE_WRITES},
        FAILOVER_STATE_FREEZE_WRITES: {FAILOVER_STATE_PRECHECK},
        FAILOVER_STATE_PRECHECK: {FAILOVER_STATE_PROMOTING, FAILOVER_STATE_FAILED},
        FAILOVER_STATE_PROMOTING: {FAILOVER_STATE_VERIFICATION, FAILOVER_STATE_FAILED},
        FAILOVER_STATE_VERIFICATION: {FAILOVER_STATE_COMPLETED, FAILOVER_STATE_FAILED},
        FAILOVER_STATE_FAILED: {FAILOVER_STATE_ROLLBACK_PENDING, FAILOVER_STATE_IDLE},
        FAILOVER_STATE_ROLLBACK_PENDING: {FAILOVER_STATE_ROLLED_BACK, FAILOVER_STATE_FAILED},
        FAILOVER_STATE_ROLLED_BACK: {FAILOVER_STATE_IDLE},
        FAILOVER_STATE_COMPLETED: {FAILOVER_STATE_IDLE, FAILOVER_STATE_ROLLBACK_PENDING},
    }
    return target in allowed.get(current, set())


def token_hash(plaintext: str) -> str:
    # Hash failover tokens so plaintext values are never stored.
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _parse_peer_regions() -> list[dict[str, Any]]:
    # Parse peer region metadata from JSON config with safe fallback.
    settings = get_settings()
    raw = settings.peer_regions_json
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _lock_key() -> str:
    settings = get_settings()
    return f"{settings.failover_redis_prefix}:lock"


def _cluster_cache_key() -> str:
    settings = get_settings()
    return f"{settings.failover_redis_prefix}:cluster_state"


async def _sync_cluster_state_cache(state: FailoverClusterState) -> None:
    # Mirror cluster state into Redis for fast reads across instances.
    redis = await get_resilience_redis()
    if redis is None:
        return
    payload = {
        "active_primary_region": state.active_primary_region,
        "epoch": str(state.epoch),
        "last_transition_at": state.last_transition_at.isoformat() if state.last_transition_at else "",
        "cooldown_until": state.cooldown_until.isoformat() if state.cooldown_until else "",
        "freeze_writes": "true" if state.freeze_writes else "false",
    }
    try:
        await redis.hset(_cluster_cache_key(), mapping=payload)
        await redis.expire(_cluster_cache_key(), 3600)
    except Exception as exc:  # noqa: BLE001 - cache failures must not block API flow
        logger.warning("failover_cluster_cache_write_failed", exc_info=exc)


async def acquire_failover_lock() -> str | None:
    # Serialize failover transitions across instances.
    redis = await get_resilience_redis()
    if redis is None:
        return None
    lock_id = uuid4().hex
    try:
        acquired = await redis.set(_lock_key(), lock_id, nx=True, ex=90)
    except Exception as exc:  # noqa: BLE001 - rely on DB row lock fallback
        logger.warning("failover_lock_acquire_failed", exc_info=exc)
        return None
    if not acquired:
        raise _failover_error("FAILOVER_IN_PROGRESS", "Another failover operation is already running", 409)
    return lock_id


async def release_failover_lock(lock_id: str | None) -> None:
    # Release Redis lock defensively without impacting API responses.
    if not lock_id:
        return
    redis = await get_resilience_redis()
    if redis is None:
        return
    try:
        current = await redis.get(_lock_key())
        if current == lock_id:
            await redis.delete(_lock_key())
    except Exception as exc:  # noqa: BLE001 - best-effort lock cleanup
        logger.warning("failover_lock_release_failed", exc_info=exc)


async def _get_or_create_cluster_state(
    session: AsyncSession,
    *,
    for_update: bool = False,
) -> FailoverClusterState:
    # Keep cluster state durable in DB for recovery from Redis loss.
    stmt = select(FailoverClusterState).where(FailoverClusterState.id == 1)
    if for_update:
        stmt = stmt.with_for_update()
    state = (await session.execute(stmt)).scalar_one_or_none()
    if state is not None:
        return state
    settings = get_settings()
    state = FailoverClusterState(
        id=1,
        active_primary_region=settings.region_id,
        epoch=1,
        last_transition_at=_utc_now(),
        cooldown_until=None,
        freeze_writes=False,
        metadata_json={"state": FAILOVER_STATE_IDLE},
    )
    session.add(state)
    await session.commit()
    await session.refresh(state)
    await _sync_cluster_state_cache(state)
    return state


async def _upsert_local_region_status(
    session: AsyncSession,
    *,
    persist: bool = False,
    allow_create_commit: bool = True,
) -> RegionStatus:
    # Keep local region status present without forcing commits on read paths.
    settings = get_settings()
    status = await session.get(RegionStatus, settings.region_id)
    now = _utc_now()
    if status is None:
        status = RegionStatus(
            region_id=settings.region_id,
            role=settings.region_role,
            health_status="healthy",
            replication_lag_seconds=0,
            last_heartbeat_at=now,
            writable=settings.region_role == "primary",
            metadata_json={},
            updated_at=now,
        )
        session.add(status)
        if allow_create_commit:
            await session.commit()
            await session.refresh(status)
        else:
            await session.flush()
        return status
    status.role = settings.region_role
    status.writable = settings.region_role == "primary"
    if persist:
        status.last_heartbeat_at = now
        status.updated_at = now
        await session.flush()
    return status


async def _check_db_writable(session: AsyncSession) -> bool:
    # Run a lightweight DB read probe to gate promotions.
    try:
        await session.execute(select(1))
        return True
    except Exception:
        return False


async def _fetch_peer_signals() -> list[dict[str, Any]]:
    # Gather peer region health signals for split-brain detection.
    peers = _parse_peer_regions()
    signals: list[dict[str, Any]] = []
    for peer in peers:
        signal: dict[str, Any] = {
            "id": peer.get("id"),
            "health_status": str(peer.get("health_status") or "unknown"),
            "active_primary_region": peer.get("active_primary_region"),
            "role": peer.get("role"),
            "writable": bool(peer.get("writable", False)),
            "source": "config",
        }
        ops_url = peer.get("ops_url")
        if isinstance(ops_url, str) and ops_url:
            try:
                async with httpx.AsyncClient(timeout=1.5) as client:
                    resp = await client.get(f"{ops_url.rstrip('/')}/v1/ops/failover/status")
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    region_info = data.get("local_region", {})
                    signal.update(
                        {
                            "health_status": region_info.get("health_status", signal["health_status"]),
                            "active_primary_region": data.get(
                                "active_primary_region", signal["active_primary_region"]
                            ),
                            "role": region_info.get("role", signal["role"]),
                            "writable": bool(region_info.get("writable", signal["writable"])),
                            "source": "ops_url",
                        }
                    )
            except Exception:
                # Keep peer status unknown when remote control-plane is unreachable.
                signal["health_status"] = "unknown"
                signal["source"] = "unreachable"
        signals.append(signal)
    return signals


async def _sync_peer_region_rows(session: AsyncSession, peer_signals: list[dict[str, Any]]) -> None:
    # Persist peer status snapshots for operator visibility and audits.
    now = _utc_now()
    for signal in peer_signals:
        region_id = signal.get("id")
        if not isinstance(region_id, str) or not region_id:
            continue
        row = await session.get(RegionStatus, region_id)
        if row is None:
            row = RegionStatus(
                region_id=region_id,
                role=str(signal.get("role") or "standby"),
                health_status=str(signal.get("health_status") or "unknown"),
                replication_lag_seconds=None,
                last_heartbeat_at=now,
                writable=bool(signal.get("writable", False)),
                metadata_json={"source": signal.get("source"), "active_primary_region": signal.get("active_primary_region")},
                updated_at=now,
            )
            session.add(row)
            continue
        row.role = str(signal.get("role") or row.role)
        row.health_status = str(signal.get("health_status") or row.health_status)
        row.writable = bool(signal.get("writable", row.writable))
        row.last_heartbeat_at = now
        row.updated_at = now
        row.metadata_json = {
            **(row.metadata_json or {}),
            "source": signal.get("source"),
            "active_primary_region": signal.get("active_primary_region"),
        }
    await session.flush()


async def evaluate_readiness(session: AsyncSession, *, persist: bool = True) -> ReadinessResult:
    # Score failover readiness with explicit blockers for operator actions.
    settings = get_settings()
    state = await _get_or_create_cluster_state(session)
    local = await _upsert_local_region_status(session)
    peer_signals = await _fetch_peer_signals()
    await _sync_peer_region_rows(session, peer_signals)
    db_writable = await _check_db_writable(session)

    blockers: list[str] = []
    score = 100

    lag = local.replication_lag_seconds
    if settings.replication_health_required:
        if lag is None:
            blockers.append("REPLICATION_LAG_UNKNOWN")
            score -= 25
        elif lag > settings.replication_lag_max_seconds:
            blockers.append("REPLICATION_LAG_TOO_HIGH")
            score -= 40

    if not db_writable or not local.writable:
        blockers.append("DB_NOT_WRITABLE")
        score -= 60

    split_brain_risk = any(
        signal.get("health_status") == "healthy"
        and signal.get("active_primary_region")
        and signal.get("active_primary_region") != settings.region_id
        for signal in peer_signals
    )
    if split_brain_risk:
        blockers.append("SPLIT_BRAIN_RISK")
        score -= 70

    if local.health_status in {"degraded", "down"}:
        blockers.append("LOCAL_REGION_UNHEALTHY")
        score -= 40

    score = max(0, min(100, score))
    recommendation = "hold"
    if state.freeze_writes:
        recommendation = "freeze_writes"
    elif not blockers and state.active_primary_region != settings.region_id:
        recommendation = "promote_candidate"
    elif state.active_primary_region == settings.region_id and local.health_status == "healthy":
        recommendation = "recover_primary"

    set_gauge(f"region_readiness_score.{settings.region_id}", float(score))
    if lag is not None:
        set_gauge(f"replication_lag_seconds.{settings.region_id}", float(lag))
    if persist:
        await session.commit()
    else:
        await session.flush()
    return ReadinessResult(
        readiness_score=score,
        recommendation=recommendation,
        blockers=blockers,
        replication_lag_seconds=lag,
        split_brain_risk=split_brain_risk,
        peer_signals=peer_signals,
    )


async def get_failover_status(session: AsyncSession) -> dict[str, Any]:
    # Return cluster state and region rows for operator visibility.
    state = await _get_or_create_cluster_state(session)
    local = await _upsert_local_region_status(session)
    rows = (
        await session.execute(select(RegionStatus).order_by(RegionStatus.region_id))
    ).scalars().all()
    return {
        "active_primary_region": state.active_primary_region,
        "epoch": state.epoch,
        "last_transition_at": state.last_transition_at.isoformat() if state.last_transition_at else None,
        "cooldown_until": state.cooldown_until.isoformat() if state.cooldown_until else None,
        "freeze_writes": state.freeze_writes,
        "local_region": {
            "id": local.region_id,
            "role": local.role,
            "health_status": local.health_status,
            "replication_lag_seconds": local.replication_lag_seconds,
            "writable": local.writable,
            "last_heartbeat_at": local.last_heartbeat_at.isoformat() if local.last_heartbeat_at else None,
        },
        "regions": [
            {
                "region_id": row.region_id,
                "role": row.role,
                "health_status": row.health_status,
                "replication_lag_seconds": row.replication_lag_seconds,
                "last_heartbeat_at": row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None,
                "writable": row.writable,
            }
            for row in rows
        ],
    }


async def issue_failover_token(
    *,
    session: AsyncSession,
    requested_by_actor_id: str | None,
    purpose: str,
    reason: str | None,
    tenant_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> FailoverTokenIssued:
    # Mint short-lived one-time tokens for promote/rollback operations.
    if purpose not in {TOKEN_PURPOSE_PROMOTE, TOKEN_PURPOSE_ROLLBACK}:
        raise _failover_error("FAILOVER_TOKEN_INVALID", "Unsupported token purpose", 400)
    settings = get_settings()
    plaintext = secrets.token_urlsafe(36)
    token_id = uuid4().hex
    expires_at = _utc_now() + timedelta(seconds=settings.failover_token_ttl_seconds)
    session.add(
        FailoverToken(
            id=token_id,
            token_hash=token_hash(plaintext),
            requested_by_actor_id=requested_by_actor_id,
            expires_at=expires_at,
            used_at=None,
            purpose=purpose,
        )
    )
    await session.commit()
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=requested_by_actor_id,
        actor_role=actor_role,
        event_type="failover.token.requested",
        outcome="success",
        resource_type="failover",
        resource_id=token_id,
        request_id=request_id,
        metadata={"purpose": purpose, "reason": reason},
        commit=True,
        best_effort=True,
    )
    return FailoverTokenIssued(token_id=token_id, token=plaintext, expires_at=expires_at)


async def _consume_token(session: AsyncSession, *, plaintext: str, purpose: str) -> FailoverToken:
    # Validate and atomically consume one-time approval tokens.
    hashed = token_hash(plaintext)
    now = _utc_now()
    token = (
        await session.execute(
            select(FailoverToken)
            .where(
                FailoverToken.token_hash == hashed,
                FailoverToken.purpose == purpose,
                FailoverToken.used_at.is_(None),
                FailoverToken.expires_at > now,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if token is None:
        raise _failover_error("FAILOVER_TOKEN_INVALID", "Invalid or expired failover token", 401)
    token.used_at = now
    await session.commit()
    await session.refresh(token)
    return token


async def _record_failover_event(
    *,
    session: AsyncSession,
    event: FailoverEvent,
    tenant_id: str | None,
    actor_role: str | None,
    event_type: str,
    outcome: str,
    request_id: str | None,
    error_code: str | None = None,
) -> None:
    # Emit audit records for each failover lifecycle transition.
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=event.requested_by_actor_id,
        actor_role=actor_role,
        event_type=event_type,
        outcome=outcome,
        resource_type="failover",
        resource_id=str(event.id),
        request_id=request_id,
        metadata={
            "from_region": event.from_region,
            "to_region": event.to_region,
            "status": event.status,
        },
        error_code=error_code,
        commit=True,
        best_effort=True,
    )


def _extract_state(report_json: dict[str, Any] | None) -> str:
    if not isinstance(report_json, dict):
        return FAILOVER_STATE_IDLE
    value = report_json.get("state")
    if isinstance(value, str):
        return value
    return FAILOVER_STATE_IDLE


async def set_write_freeze(
    *,
    session: AsyncSession,
    freeze: bool,
    reason: str | None,
    actor_id: str | None,
    actor_role: str | None,
    tenant_id: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    # Allow operators to toggle write freeze with full audit traceability.
    state = await _get_or_create_cluster_state(session, for_update=True)
    state.freeze_writes = bool(freeze)
    metadata = dict(state.metadata_json or {})
    metadata["write_freeze_reason"] = reason
    metadata["state"] = FAILOVER_STATE_FREEZE_WRITES if freeze else FAILOVER_STATE_IDLE
    state.metadata_json = metadata
    state.updated_at = _utc_now()
    await session.commit()
    await _sync_cluster_state_cache(state)
    set_gauge("write_frozen_state", 1.0 if freeze else 0.0)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="failover.write_freeze.toggled",
        outcome="success",
        resource_type="failover",
        resource_id="cluster",
        request_id=request_id,
        metadata={"freeze": freeze, "reason": reason},
        commit=True,
        best_effort=True,
    )
    return {
        "freeze_writes": state.freeze_writes,
        "active_primary_region": state.active_primary_region,
        "epoch": state.epoch,
    }


async def enforce_write_gate(
    *,
    session: AsyncSession,
    route_class: str,
    tenant_id: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
    path: str,
) -> None:
    # Block mutations/runs when this region is not writable.
    settings = get_settings()
    if not settings.failover_enabled:
        return
    if route_class not in {"mutation", "run"}:
        return

    state = await _get_or_create_cluster_state(session)
    local = await _upsert_local_region_status(session, allow_create_commit=False)
    frozen = (
        state.freeze_writes
        or state.active_primary_region != settings.region_id
        or local.role != "primary"
    )

    if (
        settings.write_freeze_on_unhealthy_replica
        and settings.replication_health_required
        and local.replication_lag_seconds is not None
        and local.replication_lag_seconds > settings.replication_lag_max_seconds
    ):
        frozen = True

    set_gauge("write_frozen_state", 1.0 if frozen else 0.0)
    if not frozen:
        return

    increment_counter("write_frozen_rejections_total")
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="failover.write_freeze.toggled",
        outcome="failure",
        resource_type="failover",
        resource_id="write_gate",
        request_id=request_id,
        metadata={
            "path": path,
            "route_class": route_class,
            "active_primary_region": state.active_primary_region,
            "region_id": settings.region_id,
            "freeze_writes": state.freeze_writes,
        },
        error_code="WRITE_FROZEN",
        commit=True,
        best_effort=True,
    )
    raise _failover_error("WRITE_FROZEN", "Writes are temporarily frozen in this region", 503)


async def _precheck_promotion(
    *,
    session: AsyncSession,
    force: bool,
) -> ReadinessResult:
    # Evaluate readiness and enforce blockers for promotion.
    readiness = await evaluate_readiness(session, persist=False)
    if readiness.split_brain_risk and not force:
        increment_counter("failover_requests_total.failed")
        raise _failover_error("SPLIT_BRAIN_RISK", "Split-brain risk detected; promotion denied", 409)
    if readiness.blockers and not force:
        increment_counter("failover_requests_total.failed")
        raise _failover_error("FAILOVER_PRECHECK_FAILED", "Failover precheck failed", 409)
    return readiness


async def promote_region(
    *,
    session: AsyncSession,
    target_region: str,
    plaintext_token: str,
    reason: str | None,
    force: bool,
    requested_by_actor_id: str | None,
    actor_role: str | None,
    tenant_id: str | None,
    request_id: str | None,
) -> FailoverTransitionResult:
    # Run token-gated promotion with lock, cooldown, and prechecks.
    started = time.monotonic()
    settings = get_settings()
    if not settings.failover_enabled:
        raise _failover_error("FAILOVER_NOT_ALLOWED", "Failover controls are disabled", 503)
    if target_region != settings.region_id:
        raise _failover_error("FAILOVER_PRECHECK_FAILED", "Target region must match local REGION_ID", 400)

    existing = (
        await session.execute(
            select(FailoverEvent)
            .where(FailoverEvent.request_id == request_id)
            .order_by(FailoverEvent.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status in {
        EVENT_STATUS_COMPLETED,
        EVENT_STATUS_FAILED,
        EVENT_STATUS_ROLLED_BACK,
    }:
        state = await _get_or_create_cluster_state(session)
        return FailoverTransitionResult(
            event_id=existing.id,
            status=existing.status,
            from_region=existing.from_region,
            to_region=existing.to_region,
            epoch=state.epoch,
            freeze_writes=state.freeze_writes,
            blockers=list((existing.report_json or {}).get("blockers", [])),
        )

    lock_id = await acquire_failover_lock()
    try:
        state = await _get_or_create_cluster_state(session, for_update=True)
        now = _utc_now()
        if state.cooldown_until and state.cooldown_until > now:
            raise _failover_error("FAILOVER_COOLDOWN_ACTIVE", "Failover cooldown is still active", 409)

        token = await _consume_token(session, plaintext=plaintext_token, purpose=TOKEN_PURPOSE_PROMOTE)
        event = FailoverEvent(
            from_region=state.active_primary_region,
            to_region=target_region,
            mode=settings.failover_mode,
            status=EVENT_STATUS_REQUESTED,
            reason=reason,
            requested_by_actor_id=requested_by_actor_id,
            approval_token_id=token.id,
            request_id=request_id,
            report_json={"state": FAILOVER_STATE_IDLE, "state_history": [FAILOVER_STATE_IDLE], "blockers": []},
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        await _record_failover_event(
            session=session,
            event=event,
            tenant_id=tenant_id,
            actor_role=actor_role,
            event_type="failover.promote.requested",
            outcome="success",
            request_id=request_id,
        )
        try:
            state_name = _extract_state(event.report_json)
            if settings.write_freeze_on_unhealthy_replica and _state_transition_allowed(
                state_name, FAILOVER_STATE_FREEZE_WRITES
            ):
                state.freeze_writes = True
                set_gauge("write_frozen_state", 1.0)
                report = dict(event.report_json or {})
                history = list(report.get("state_history", []))
                history.append(FAILOVER_STATE_FREEZE_WRITES)
                report["state"] = FAILOVER_STATE_FREEZE_WRITES
                report["state_history"] = history
                event.report_json = report
                await session.commit()

            readiness = await _precheck_promotion(session=session, force=force)
            report = dict(event.report_json or {})
            history = list(report.get("state_history", []))
            history.append(FAILOVER_STATE_PRECHECK)
            report["state"] = FAILOVER_STATE_PRECHECK
            report["state_history"] = history
            report["blockers"] = readiness.blockers
            report["readiness_score"] = readiness.readiness_score
            event.report_json = report
            event.status = EVENT_STATUS_VALIDATED
            await session.commit()

            history.append(FAILOVER_STATE_PROMOTING)
            report["state"] = FAILOVER_STATE_PROMOTING
            report["state_history"] = history
            event.report_json = report
            event.status = EVENT_STATUS_EXECUTING
            state.active_primary_region = target_region
            state.epoch = int(state.epoch) + 1
            state.last_transition_at = now
            state.cooldown_until = now + timedelta(seconds=settings.failover_cooldown_seconds)
            state.metadata_json = {
                **(state.metadata_json or {}),
                "state": FAILOVER_STATE_PROMOTING,
                "previous_primary": event.from_region,
            }
            await session.commit()

            history.append(FAILOVER_STATE_VERIFICATION)
            report["state"] = FAILOVER_STATE_VERIFICATION
            report["state_history"] = history
            event.report_json = report
            await session.commit()

            # Verification uses a DB probe and local region writable status.
            db_writable = await _check_db_writable(session)
            local = await _upsert_local_region_status(session, allow_create_commit=False)
            if not db_writable or not local.writable:
                history.append(FAILOVER_STATE_FAILED)
                event.status = EVENT_STATUS_FAILED
                event.error_code = "FAILOVER_PRECHECK_FAILED"
                event.error_message = "Verification failed: local region not writable"
                event.completed_at = _utc_now()
                report["state"] = FAILOVER_STATE_FAILED
                report["state_history"] = history
                event.report_json = report
                state.metadata_json = {**(state.metadata_json or {}), "state": FAILOVER_STATE_FAILED}
                await session.commit()
                increment_counter("failover_requests_total.failed")
                await _record_failover_event(
                    session=session,
                    event=event,
                    tenant_id=tenant_id,
                    actor_role=actor_role,
                    event_type="failover.promote.failed",
                    outcome="failure",
                    request_id=request_id,
                    error_code="FAILOVER_PRECHECK_FAILED",
                )
                set_gauge("failover_duration_ms", (time.monotonic() - started) * 1000.0)
                raise _failover_error("FAILOVER_PRECHECK_FAILED", "Verification failed after promotion", 409)

            state.freeze_writes = False
            set_gauge("write_frozen_state", 0.0)
            history.append(FAILOVER_STATE_COMPLETED)
            event.status = EVENT_STATUS_COMPLETED
            event.completed_at = _utc_now()
            report["state"] = FAILOVER_STATE_COMPLETED
            report["state_history"] = history
            event.report_json = report
            state.metadata_json = {**(state.metadata_json or {}), "state": FAILOVER_STATE_COMPLETED}
            await session.commit()
            await _sync_cluster_state_cache(state)

            increment_counter("failover_requests_total.completed")
            set_gauge("failover_duration_ms", (time.monotonic() - started) * 1000.0)
            await _record_failover_event(
                session=session,
                event=event,
                tenant_id=tenant_id,
                actor_role=actor_role,
                event_type="failover.promote.completed",
                outcome="success",
                request_id=request_id,
            )
            return FailoverTransitionResult(
                event_id=event.id,
                status=event.status,
                from_region=event.from_region,
                to_region=event.to_region,
                epoch=state.epoch,
                freeze_writes=state.freeze_writes,
                blockers=readiness.blockers,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            event.status = EVENT_STATUS_FAILED
            event.completed_at = _utc_now()
            event.error_code = str(detail.get("code") or "FAILOVER_PRECHECK_FAILED")
            event.error_message = str(detail.get("message") or "Failover failed")
            report = dict(event.report_json or {})
            history = list(report.get("state_history", []))
            if not history or history[-1] != FAILOVER_STATE_FAILED:
                history.append(FAILOVER_STATE_FAILED)
            report["state"] = FAILOVER_STATE_FAILED
            report["state_history"] = history
            report["blockers"] = report.get("blockers", [])
            event.report_json = report
            # Release write freeze on precheck failures where promotion never finalized.
            if event.to_region != state.active_primary_region:
                state.freeze_writes = False
                set_gauge("write_frozen_state", 0.0)
            state.metadata_json = {**(state.metadata_json or {}), "state": FAILOVER_STATE_FAILED}
            await session.commit()
            increment_counter("failover_requests_total.failed")
            set_gauge("failover_duration_ms", (time.monotonic() - started) * 1000.0)
            await _record_failover_event(
                session=session,
                event=event,
                tenant_id=tenant_id,
                actor_role=actor_role,
                event_type="failover.promote.failed",
                outcome="failure",
                request_id=request_id,
                error_code=event.error_code,
            )
            raise
    finally:
        await release_failover_lock(lock_id)


async def rollback_failover(
    *,
    session: AsyncSession,
    plaintext_token: str,
    reason: str | None,
    requested_by_actor_id: str | None,
    actor_role: str | None,
    tenant_id: str | None,
    request_id: str | None,
) -> FailoverTransitionResult:
    # Roll back primary assignment using a dedicated one-time token.
    started = time.monotonic()
    settings = get_settings()
    if not settings.failover_enabled:
        raise _failover_error("FAILOVER_NOT_ALLOWED", "Failover controls are disabled", 503)

    lock_id = await acquire_failover_lock()
    try:
        state = await _get_or_create_cluster_state(session, for_update=True)
        now = _utc_now()
        if state.cooldown_until and state.cooldown_until > now:
            raise _failover_error("FAILOVER_COOLDOWN_ACTIVE", "Failover cooldown is still active", 409)

        token = await _consume_token(session, plaintext=plaintext_token, purpose=TOKEN_PURPOSE_ROLLBACK)
        previous_primary = (state.metadata_json or {}).get("previous_primary")
        if not isinstance(previous_primary, str) or not previous_primary:
            raise _failover_error("FAILOVER_NOT_ALLOWED", "No previous primary available for rollback", 409)

        event = FailoverEvent(
            from_region=state.active_primary_region,
            to_region=previous_primary,
            mode=settings.failover_mode,
            status=EVENT_STATUS_EXECUTING,
            reason=reason,
            requested_by_actor_id=requested_by_actor_id,
            approval_token_id=token.id,
            request_id=request_id,
            report_json={
                "state": FAILOVER_STATE_ROLLBACK_PENDING,
                "state_history": [FAILOVER_STATE_ROLLBACK_PENDING],
            },
        )
        session.add(event)
        state.active_primary_region = previous_primary
        state.epoch = int(state.epoch) + 1
        state.last_transition_at = now
        state.cooldown_until = now + timedelta(seconds=settings.failover_cooldown_seconds)
        state.freeze_writes = False
        state.metadata_json = {**(state.metadata_json or {}), "state": FAILOVER_STATE_ROLLED_BACK}
        event.status = EVENT_STATUS_ROLLED_BACK
        event.completed_at = _utc_now()
        event.report_json = {
            "state": FAILOVER_STATE_ROLLED_BACK,
            "state_history": [FAILOVER_STATE_ROLLBACK_PENDING, FAILOVER_STATE_ROLLED_BACK],
        }
        await session.commit()
        await session.refresh(event)
        await _sync_cluster_state_cache(state)

        increment_counter("failover_requests_total.rolled_back")
        set_gauge("failover_duration_ms", (time.monotonic() - started) * 1000.0)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=requested_by_actor_id,
            actor_role=actor_role,
            event_type="failover.rollback.completed",
            outcome="success",
            resource_type="failover",
            resource_id=str(event.id),
            request_id=request_id,
            metadata={"from_region": event.from_region, "to_region": event.to_region},
            commit=True,
            best_effort=True,
        )
        return FailoverTransitionResult(
            event_id=event.id,
            status=event.status,
            from_region=event.from_region,
            to_region=event.to_region,
            epoch=state.epoch,
            freeze_writes=state.freeze_writes,
            blockers=[],
        )
    except HTTPException:
        increment_counter("failover_requests_total.failed")
        set_gauge("failover_duration_ms", (time.monotonic() - started) * 1000.0)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=requested_by_actor_id,
            actor_role=actor_role,
            event_type="failover.rollback.failed",
            outcome="failure",
            resource_type="failover",
            resource_id="rollback",
            request_id=request_id,
            metadata={"reason": reason},
            error_code="FAILOVER_NOT_ALLOWED",
            commit=True,
            best_effort=True,
        )
        raise
    finally:
        await release_failover_lock(lock_id)
