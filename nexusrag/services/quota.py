from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hmac
import hashlib
import json
import logging
import random
from typing import Any, Callable

import httpx
from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import PlanLimit, QuotaSoftCapEvent, UsageCounter
from nexusrag.services.audit import get_request_context, record_event


logger = logging.getLogger(__name__)

_PERIOD_DAY = "day"
_PERIOD_MONTH = "month"

_METRIC_REQUESTS = "requests"

_USAGE_SAMPLE_RATE = 0.02


@dataclass(frozen=True)
class QuotaSnapshot:
    # Capture limit and usage for a period for header rendering and errors.
    limit: int | None
    used: int
    remaining: int | None


@dataclass(frozen=True)
class QuotaResult:
    # Summarize quota enforcement and headers for the current request.
    allowed: bool
    day: QuotaSnapshot
    month: QuotaSnapshot
    soft_cap_reached: bool
    hard_cap_mode: str
    blocked_period: str | None = None


class PrincipalLike:
    # Minimal principal view for quota enforcement.
    tenant_id: str
    api_key_id: str
    role: str


class QuotaService:
    def __init__(self, *, time_provider: Callable[[], datetime] | None = None) -> None:
        # Allow time injection for deterministic rollover tests.
        self._time_provider = time_provider or _utc_now

    async def check_and_consume_quota(
        self,
        *,
        session: AsyncSession,
        principal: PrincipalLike,
        estimated_cost: int = 1,
    ) -> QuotaResult:
        # Enforce per-tenant quotas and increment counters atomically.
        now = self._time_provider()
        day_start = _day_start(now)
        month_start = _month_start(now)

        in_transaction = session.in_transaction()
        # Use a nested transaction when prior reads have already opened one.
        tx_context = session.begin_nested() if in_transaction else session.begin()
        async with tx_context:
            plan = await _get_plan_limit(session, principal.tenant_id)
            soft_cap_ratio = plan.soft_cap_ratio if plan else 0.8
            hard_cap_enabled = plan.hard_cap_enabled if plan else True

            daily_limit = plan.daily_requests_limit if plan else None
            monthly_limit = plan.monthly_requests_limit if plan else None

            hard_cap_mode = "enforce" if hard_cap_enabled else "observe"
            day_counter = await _get_or_create_counter(
                session, principal.tenant_id, _PERIOD_DAY, day_start
            )
            month_counter = await _get_or_create_counter(
                session, principal.tenant_id, _PERIOD_MONTH, month_start
            )

            day_used = int(day_counter.requests_count or 0)
            month_used = int(month_counter.requests_count or 0)

            day_proposed = day_used + estimated_cost
            month_proposed = month_used + estimated_cost

            day_exceeded = daily_limit is not None and day_proposed > daily_limit
            month_exceeded = monthly_limit is not None and month_proposed > monthly_limit

            if hard_cap_enabled and (day_exceeded or month_exceeded):
                blocked_period = _PERIOD_MONTH if month_exceeded else _PERIOD_DAY
                day_snapshot = _snapshot(daily_limit, day_used)
                month_snapshot = _snapshot(monthly_limit, month_used)
                return QuotaResult(
                    allowed=False,
                    day=day_snapshot,
                    month=month_snapshot,
                    soft_cap_reached=_soft_cap_reached(day_snapshot, month_snapshot, soft_cap_ratio),
                    hard_cap_mode=hard_cap_mode,
                    blocked_period=blocked_period,
                )

            # Increment counters for allowed or overage-observed requests.
            day_counter.requests_count = day_proposed
            month_counter.requests_count = month_proposed

            day_snapshot = _snapshot(daily_limit, day_proposed)
            month_snapshot = _snapshot(monthly_limit, month_proposed)

            soft_cap_reached = _soft_cap_reached(day_snapshot, month_snapshot, soft_cap_ratio)
            soft_cap_periods: list[str] = []
            if soft_cap_reached:
                soft_cap_periods = await _insert_soft_cap_event(
                    session,
                    tenant_id=principal.tenant_id,
                    day_snapshot=day_snapshot,
                    month_snapshot=month_snapshot,
                    day_start=day_start,
                    month_start=month_start,
                    soft_cap_ratio=soft_cap_ratio,
                )

        if in_transaction:
            # Commit counters when we piggyback on an existing transaction.
            await session.commit()

        await _emit_usage_events(
            session=session,
            principal=principal,
            day_snapshot=day_snapshot,
            month_snapshot=month_snapshot,
            soft_cap_ratio=soft_cap_ratio,
            soft_cap_periods=soft_cap_periods,
            hard_cap_enabled=hard_cap_enabled,
        )

        return QuotaResult(
            allowed=True,
            day=day_snapshot,
            month=month_snapshot,
            soft_cap_reached=soft_cap_reached,
            hard_cap_mode=hard_cap_mode,
        )


_quota_service: QuotaService | None = None


def get_quota_service() -> QuotaService:
    # Cache the quota service for reuse across requests.
    global _quota_service
    if _quota_service is None:
        _quota_service = QuotaService()
    return _quota_service


def reset_quota_service() -> None:
    # Reset cached services for deterministic tests.
    global _quota_service
    _quota_service = None


def _utc_now() -> datetime:
    # Use UTC for consistent quota period boundaries.
    return datetime.now(timezone.utc)


def _day_start(now: datetime) -> datetime:
    # Normalize to the UTC day boundary for daily quotas.
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _month_start(now: datetime) -> datetime:
    # Normalize to the UTC month boundary for monthly quotas.
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _snapshot(limit: int | None, used: int) -> QuotaSnapshot:
    # Compute remaining values while preserving unlimited semantics.
    if limit is None:
        return QuotaSnapshot(limit=None, used=used, remaining=None)
    remaining = max(limit - used, 0)
    return QuotaSnapshot(limit=limit, used=used, remaining=remaining)


def _soft_cap_reached(
    day_snapshot: QuotaSnapshot,
    month_snapshot: QuotaSnapshot,
    ratio: float,
) -> bool:
    # Evaluate whether either period has crossed its soft cap threshold.
    return _period_soft_cap_reached(day_snapshot, ratio) or _period_soft_cap_reached(
        month_snapshot, ratio
    )


def _period_soft_cap_reached(snapshot: QuotaSnapshot, ratio: float) -> bool:
    # Guard against invalid ratios and unlimited plans.
    if snapshot.limit is None or snapshot.limit <= 0:
        return False
    threshold = snapshot.limit * ratio
    return snapshot.used >= threshold


def _period_exceeded(snapshot: QuotaSnapshot) -> bool:
    # Use remaining counts to detect overage after increment.
    if snapshot.limit is None:
        return False
    return snapshot.used > snapshot.limit


def _format_limit(value: int | None) -> str:
    # Represent unlimited limits using the agreed header token.
    return "unlimited" if value is None else str(value)


def _format_remaining(value: int | None) -> str:
    # Represent unlimited remaining with the agreed header token.
    return "unlimited" if value is None else str(value)


def quota_headers(result: QuotaResult) -> dict[str, str]:
    # Render quota headers for responses with consistent casing.
    return {
        "X-Quota-Day-Limit": _format_limit(result.day.limit),
        "X-Quota-Day-Used": str(result.day.used),
        "X-Quota-Day-Remaining": _format_remaining(result.day.remaining),
        "X-Quota-Month-Limit": _format_limit(result.month.limit),
        "X-Quota-Month-Used": str(result.month.used),
        "X-Quota-Month-Remaining": _format_remaining(result.month.remaining),
        "X-Quota-SoftCap-Reached": "true" if result.soft_cap_reached else "false",
        "X-Quota-HardCap-Mode": result.hard_cap_mode,
    }


def build_quota_exception(result: QuotaResult) -> HTTPException:
    # Construct stable 402 payloads with period and usage details.
    period = result.blocked_period or _PERIOD_MONTH
    if period == _PERIOD_DAY:
        snapshot = result.day
        message = "Daily request quota exceeded"
    else:
        snapshot = result.month
        message = "Monthly request quota exceeded"

    detail = {
        "code": "QUOTA_EXCEEDED",
        "message": message,
        "period": period,
        "limit": snapshot.limit,
        "used": snapshot.used if snapshot.limit is None else min(snapshot.used, snapshot.limit),
        "remaining": 0 if snapshot.limit is not None else "unlimited",
    }

    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=detail,
        headers=quota_headers(result),
    )


async def enforce_quota(
    *,
    request: Request,
    response: Response,
    principal: PrincipalLike,
    db: AsyncSession,
    estimated_cost: int,
) -> None:
    # Enforce quotas in the request pipeline after rate limiting.
    service = get_quota_service()
    result = await service.check_and_consume_quota(
        session=db, principal=principal, estimated_cost=estimated_cost
    )

    if not result.allowed:
        await _emit_hard_cap_blocked(
            db=db,
            principal=principal,
            request=request,
            result=result,
        )
        raise build_quota_exception(result)

    for key, value in quota_headers(result).items():
        response.headers[key] = value

    await _emit_overage_if_needed(db, principal, request, result)


def _billing_signature(secret: str, payload: bytes) -> str:
    # Compute HMAC SHA256 signature for billing webhook payloads.
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


async def _send_webhook(event_type: str, payload: dict[str, Any]) -> None:
    # Post signed billing payloads without blocking request success.
    settings = get_settings()
    if not settings.billing_webhook_enabled:
        return
    if not settings.billing_webhook_url or not settings.billing_webhook_secret:
        logger.warning("billing_webhook_missing_config")
        return

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = _billing_signature(settings.billing_webhook_secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-Billing-Signature": signature,
        "X-Billing-Event": event_type,
    }

    timeout = settings.billing_webhook_timeout_ms / 1000.0
    async with httpx.AsyncClient(timeout=timeout) as client:
        await client.post(settings.billing_webhook_url, content=body, headers=headers)


async def _emit_usage_events(
    *,
    session: AsyncSession,
    principal: PrincipalLike,
    day_snapshot: QuotaSnapshot,
    month_snapshot: QuotaSnapshot,
    soft_cap_ratio: float,
    soft_cap_periods: list[str],
    hard_cap_enabled: bool,
) -> None:
    # Emit soft-cap and usage-recorded events without blocking request flow.
    for period in soft_cap_periods:
        snapshot = day_snapshot if period == _PERIOD_DAY else month_snapshot
        await record_event(
            session=session,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="quota.soft_cap_reached",
            outcome="success",
            resource_type="quota",
            metadata={
                "period": period,
                "used": snapshot.used,
                "limit": snapshot.limit,
                "soft_cap_ratio": soft_cap_ratio,
            },
            commit=True,
            best_effort=True,
        )

        await _safe_webhook(
            event_type="quota.soft_cap_reached",
            payload={
                "event_type": "quota.soft_cap_reached",
                "tenant_id": principal.tenant_id,
                "period": period,
                "used": snapshot.used,
                "limit": snapshot.limit,
                "soft_cap_ratio": soft_cap_ratio,
                "timestamp": _utc_now().isoformat(),
            },
            session=session,
            tenant_id=principal.tenant_id,
        )

    if random.random() < _USAGE_SAMPLE_RATE:
        await record_event(
            session=session,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="billing.usage_recorded",
            outcome="success",
            resource_type="quota",
            metadata={
                "day_used": day_snapshot.used,
                "day_limit": day_snapshot.limit,
                "month_used": month_snapshot.used,
                "month_limit": month_snapshot.limit,
                "hard_cap_enabled": hard_cap_enabled,
            },
            commit=True,
            best_effort=True,
        )


async def _emit_hard_cap_blocked(
    *,
    db: AsyncSession,
    principal: PrincipalLike,
    request: Request,
    result: QuotaResult,
) -> None:
    # Record hard-cap blocks before returning 402 to clients.
    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="quota.hard_cap_blocked",
        outcome="failure",
        resource_type="quota",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "period": result.blocked_period,
            "day_used": result.day.used,
            "day_limit": result.day.limit,
            "month_used": result.month.used,
            "month_limit": result.month.limit,
        },
        commit=True,
        best_effort=True,
    )

    await _safe_webhook(
        event_type="quota.hard_cap_blocked",
        payload={
            "event_type": "quota.hard_cap_blocked",
            "tenant_id": principal.tenant_id,
            "period": result.blocked_period,
            "day_used": result.day.used,
            "day_limit": result.day.limit,
            "month_used": result.month.used,
            "month_limit": result.month.limit,
            "timestamp": _utc_now().isoformat(),
        },
        session=db,
        tenant_id=principal.tenant_id,
    )


async def _emit_overage_if_needed(
    db: AsyncSession,
    principal: PrincipalLike,
    request: Request,
    result: QuotaResult,
) -> None:
    # Emit overage events when hard cap is in observe mode and usage exceeds limits.
    if result.hard_cap_mode != "observe":
        return

    day_over = _period_exceeded(result.day)
    month_over = _period_exceeded(result.month)
    if not day_over and not month_over:
        return

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="quota.overage_observed",
        outcome="success",
        resource_type="quota",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "day_used": result.day.used,
            "day_limit": result.day.limit,
            "month_used": result.month.used,
            "month_limit": result.month.limit,
        },
        commit=True,
        best_effort=True,
    )


async def _safe_webhook(
    *,
    event_type: str,
    payload: dict[str, Any],
    session: AsyncSession,
    tenant_id: str,
) -> None:
    # Fire webhook calls and log failures without breaking request flows.
    try:
        await _send_webhook(event_type, payload)
    except Exception as exc:  # noqa: BLE001 - webhook failures are non-fatal
        logger.warning("billing_webhook_failed event_type=%s", event_type, exc_info=exc)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id="billing_webhook",
            actor_role=None,
            event_type="billing.webhook.failure",
            outcome="failure",
            resource_type="billing",
            metadata={"event_type": event_type},
            commit=True,
            best_effort=True,
        )


async def _get_plan_limit(session: AsyncSession, tenant_id: str) -> PlanLimit | None:
    # Fetch quota limits for the tenant, if configured.
    result = await session.execute(select(PlanLimit).where(PlanLimit.tenant_id == tenant_id))
    return result.scalar_one_or_none()


async def _get_or_create_counter(
    session: AsyncSession,
    tenant_id: str,
    period_type: str,
    period_start: datetime,
) -> UsageCounter:
    # Lock usage counters to ensure atomic increments.
    stmt = (
        select(UsageCounter)
        .where(
            UsageCounter.tenant_id == tenant_id,
            UsageCounter.period_type == period_type,
            UsageCounter.period_start == period_start,
        )
        .with_for_update()
    )
    result = await session.execute(stmt)
    counter = result.scalar_one_or_none()
    if counter is None:
        counter = UsageCounter(
            tenant_id=tenant_id,
            period_type=period_type,
            period_start=period_start,
            requests_count=0,
        )
        session.add(counter)
    return counter


async def _insert_soft_cap_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    day_snapshot: QuotaSnapshot,
    month_snapshot: QuotaSnapshot,
    day_start: datetime,
    month_start: datetime,
    soft_cap_ratio: float,
) -> list[str]:
    # Insert soft-cap markers with dedupe per period/metric.
    inserted: list[str] = []
    if _period_soft_cap_reached(day_snapshot, soft_cap_ratio):
        if await _try_insert_soft_cap(
            session,
            tenant_id=tenant_id,
            period_type=_PERIOD_DAY,
            period_start=day_start,
        ):
            inserted.append(_PERIOD_DAY)
    if _period_soft_cap_reached(month_snapshot, soft_cap_ratio):
        if await _try_insert_soft_cap(
            session,
            tenant_id=tenant_id,
            period_type=_PERIOD_MONTH,
            period_start=month_start,
        ):
            inserted.append(_PERIOD_MONTH)
    return inserted


async def _try_insert_soft_cap(
    session: AsyncSession,
    *,
    tenant_id: str,
    period_type: str,
    period_start: datetime,
) -> bool:
    # Add soft-cap dedupe rows without aborting the main transaction.
    try:
        async with session.begin_nested():
            session.add(
                QuotaSoftCapEvent(
                    tenant_id=tenant_id,
                    period_type=period_type,
                    period_start=period_start,
                    metric=_METRIC_REQUESTS,
                )
            )
        return True
    except IntegrityError:
        return False
    except SQLAlchemyError as exc:
        logger.warning("quota_soft_cap_insert_failed", exc_info=exc)
        return False


def parse_period_start(period: str, start: date) -> datetime:
    # Normalize date inputs into UTC period boundaries for admin usage queries.
    if period == _PERIOD_MONTH:
        return datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    return datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
