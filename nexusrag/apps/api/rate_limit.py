from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import math
import random
import time
from typing import Callable, Protocol

from fastapi import HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.services.audit import get_request_context, record_event


logger = logging.getLogger(__name__)

ROUTE_CLASS_RUN = "run"
ROUTE_CLASS_MUTATION = "mutation"
ROUTE_CLASS_READ = "read"
ROUTE_CLASS_OPS = "ops"

_RUN_WEIGHT = 3

_DEGRADED_SAMPLE_RATE = 0.05


class PrincipalLike(Protocol):
    # Minimal principal shape needed for rate limiting.
    api_key_id: str
    tenant_id: str
    role: str


@dataclass(frozen=True)
class BucketConfig:
    # Configure rate limits with a sustained rate and burst capacity.
    rps: float
    burst: int


@dataclass(frozen=True)
class RouteLimitConfig:
    # Keep key and tenant buckets separate to enforce dual-scoped limits.
    key: BucketConfig
    tenant: BucketConfig


@dataclass(frozen=True)
class RateLimitDecision:
    # Capture the outcome and retry hints for a rate-limited request.
    allowed: bool
    route_class: str
    scope: str | None
    retry_after_ms: int
    key_remaining: float | None = None
    tenant_remaining: float | None = None
    degraded: bool = False


_TOKEN_BUCKET_LUA = r"""
local now_ms = tonumber(ARGV[1])
local key_rate = tonumber(ARGV[2])
local key_burst = tonumber(ARGV[3])
local key_cost = tonumber(ARGV[4])
local key_ttl = tonumber(ARGV[5])
local tenant_rate = tonumber(ARGV[6])
local tenant_burst = tonumber(ARGV[7])
local tenant_cost = tonumber(ARGV[8])
local tenant_ttl = tonumber(ARGV[9])

local function get_tokens(key, rate, burst)
  local data = redis.call("HMGET", key, "tokens", "ts")
  local tokens = tonumber(data[1])
  local ts = tonumber(data[2])
  if tokens == nil then
    tokens = burst
    ts = now_ms
  end
  if now_ms < ts then
    ts = now_ms
  end
  local delta = (now_ms - ts) / 1000.0
  local refill = delta * rate
  tokens = math.min(burst, tokens + refill)
  return tokens
end

local function retry_after_ms(tokens, rate, cost)
  if tokens >= cost then
    return 0
  end
  if rate <= 0 then
    return 1000
  end
  local needed = cost - tokens
  return math.ceil((needed / rate) * 1000)
end

local key_tokens = get_tokens(KEYS[1], key_rate, key_burst)
local tenant_tokens = get_tokens(KEYS[2], tenant_rate, tenant_burst)

local key_allowed = key_tokens >= key_cost
local tenant_allowed = tenant_tokens >= tenant_cost
local allowed = key_allowed and tenant_allowed

local key_retry = retry_after_ms(key_tokens, key_rate, key_cost)
local tenant_retry = retry_after_ms(tenant_tokens, tenant_rate, tenant_cost)

if allowed then
  key_tokens = key_tokens - key_cost
  tenant_tokens = tenant_tokens - tenant_cost
end

redis.call("HMSET", KEYS[1], "tokens", key_tokens, "ts", now_ms)
redis.call("HMSET", KEYS[2], "tokens", tenant_tokens, "ts", now_ms)
redis.call("EXPIRE", KEYS[1], key_ttl)
redis.call("EXPIRE", KEYS[2], tenant_ttl)

return {allowed and 1 or 0, key_allowed and 1 or 0, key_tokens, key_retry, tenant_allowed and 1 or 0, tenant_tokens, tenant_retry}
"""


_redis_pool: Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None
_redis_lock = asyncio.Lock()


def route_class_for_path(path: str, method: str) -> tuple[str, int]:
    # Map raw path/method inputs into route classes for rate limiting and analytics.
    normalized_method = method.upper()

    if path == "/run":
        return ROUTE_CLASS_RUN, _RUN_WEIGHT

    if path.startswith("/ops/"):
        return ROUTE_CLASS_OPS, 1

    if path.startswith("/audit/events"):
        return ROUTE_CLASS_OPS, 1

    if normalized_method in {"POST", "PATCH", "DELETE"}:
        if (
            path.startswith("/documents")
            or path.startswith("/corpora")
            or path.startswith("/audit")
            or path.startswith("/admin")
            or path.startswith("/self-serve")
        ):
            return ROUTE_CLASS_MUTATION, 1

    return ROUTE_CLASS_READ, 1


def route_class_for_request(request: Request) -> tuple[str, int]:
    # Map request paths/methods into rate limit route classes with weights.
    return route_class_for_path(request.url.path, request.method)


def _calculate_tokens(
    *,
    tokens: float | None,
    last_ms: int | None,
    now_ms: int,
    rate: float,
    burst: int,
) -> float:
    # Refill tokens based on elapsed time while enforcing burst capacity.
    if tokens is None:
        tokens = float(burst)
    if last_ms is None:
        last_ms = now_ms
    if now_ms < last_ms:
        last_ms = now_ms
    delta_s = (now_ms - last_ms) / 1000.0
    tokens = min(float(burst), tokens + (delta_s * rate))
    return tokens


def _retry_after_ms(tokens: float, *, rate: float, cost: int) -> int:
    # Compute retry-after using the token deficit and sustained rate.
    if tokens >= cost:
        return 0
    if rate <= 0:
        return 1000
    needed = cost - tokens
    return int(math.ceil((needed / rate) * 1000))


def _ttl_seconds(rate: float, burst: int) -> int:
    # Expire idle buckets after a conservative refill window.
    if rate <= 0:
        return max(1, burst)
    return max(1, int(math.ceil((burst / rate) * 2)))


async def _get_redis() -> Redis:
    # Cache Redis connections to avoid reconnecting per request.
    global _redis_pool, _redis_loop
    current_loop = asyncio.get_running_loop()
    if _redis_pool is not None and _redis_loop == current_loop:
        return _redis_pool
    if _redis_pool is not None and _redis_loop != current_loop:
        _redis_pool = None
    async with _redis_lock:
        if _redis_pool is None:
            settings = get_settings()
            _redis_pool = Redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            _redis_loop = current_loop
    return _redis_pool


class RateLimiter:
    def __init__(self, *, time_provider: Callable[[], float] | None = None) -> None:
        # Allow injecting time for deterministic tests.
        self._time_provider = time_provider or time.time

    async def check(
        self,
        *,
        api_key_id: str,
        tenant_id: str,
        route_class: str,
        cost: int,
        limits: RouteLimitConfig,
    ) -> RateLimitDecision:
        # Evaluate the key and tenant buckets atomically in Redis.
        settings = get_settings()
        prefix = settings.rl_redis_prefix
        key_bucket = f"{prefix}:key:{api_key_id}:{route_class}"
        tenant_bucket = f"{prefix}:tenant:{tenant_id}:{route_class}"
        now_ms = int(self._time_provider() * 1000)

        key_ttl = _ttl_seconds(limits.key.rps, limits.key.burst)
        tenant_ttl = _ttl_seconds(limits.tenant.rps, limits.tenant.burst)

        redis = await _get_redis()
        result = await redis.eval(
            _TOKEN_BUCKET_LUA,
            2,
            key_bucket,
            tenant_bucket,
            now_ms,
            limits.key.rps,
            limits.key.burst,
            cost,
            key_ttl,
            limits.tenant.rps,
            limits.tenant.burst,
            cost,
            tenant_ttl,
        )

        allowed = int(result[0]) == 1
        key_allowed = int(result[1]) == 1
        key_tokens = float(result[2])
        key_retry = int(float(result[3]))
        tenant_allowed = int(result[4]) == 1
        tenant_tokens = float(result[5])
        tenant_retry = int(float(result[6]))

        if allowed:
            return RateLimitDecision(
                allowed=True,
                route_class=route_class,
                scope=None,
                retry_after_ms=0,
                key_remaining=key_tokens,
                tenant_remaining=tenant_tokens,
            )

        scope = "api_key"
        retry_after_ms = key_retry
        if key_allowed and not tenant_allowed:
            scope = "tenant"
            retry_after_ms = tenant_retry
        elif not key_allowed and not tenant_allowed:
            if tenant_retry > key_retry:
                scope = "tenant"
                retry_after_ms = tenant_retry

        return RateLimitDecision(
            allowed=False,
            route_class=route_class,
            scope=scope,
            retry_after_ms=retry_after_ms,
            key_remaining=key_tokens,
            tenant_remaining=tenant_tokens,
        )


_rate_limiter: RateLimiter | None = None


def _get_rate_limiter() -> RateLimiter:
    # Cache the rate limiter so requests share Redis connections and time provider.
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def reset_rate_limiter_state() -> None:
    # Reset cached Redis connections for deterministic test setup.
    global _rate_limiter, _redis_pool, _redis_loop
    _rate_limiter = None
    _redis_pool = None
    _redis_loop = None


def _limits_for_route(route_class: str) -> RouteLimitConfig:
    # Select key/tenant thresholds for the given route class.
    settings = get_settings()
    if route_class == ROUTE_CLASS_RUN:
        return RouteLimitConfig(
            key=BucketConfig(settings.rl_key_run_rps, settings.rl_key_run_burst),
            tenant=BucketConfig(settings.rl_tenant_run_rps, settings.rl_tenant_run_burst),
        )
    if route_class == ROUTE_CLASS_MUTATION:
        return RouteLimitConfig(
            key=BucketConfig(settings.rl_key_mutation_rps, settings.rl_key_mutation_burst),
            tenant=BucketConfig(
                settings.rl_tenant_mutation_rps, settings.rl_tenant_mutation_burst
            ),
        )
    if route_class == ROUTE_CLASS_OPS:
        return RouteLimitConfig(
            key=BucketConfig(settings.rl_key_ops_rps, settings.rl_key_ops_burst),
            tenant=BucketConfig(settings.rl_tenant_ops_rps, settings.rl_tenant_ops_burst),
        )
    return RouteLimitConfig(
        key=BucketConfig(settings.rl_key_read_rps, settings.rl_key_read_burst),
        tenant=BucketConfig(settings.rl_tenant_read_rps, settings.rl_tenant_read_burst),
    )


def _throttle_exception(*, decision: RateLimitDecision) -> HTTPException:
    # Construct a stable 429 response with retry hints and metadata.
    retry_after_s = int(math.ceil(decision.retry_after_ms / 1000.0))
    headers = {
        "Retry-After": str(retry_after_s),
        "X-RateLimit-Scope": decision.scope or "unknown",
        "X-RateLimit-Route-Class": decision.route_class,
        "X-RateLimit-Retry-After-Ms": str(decision.retry_after_ms),
    }
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "RATE_LIMITED",
            "message": "Rate limit exceeded",
            "scope": decision.scope or "unknown",
            "route_class": decision.route_class,
            "retry_after_ms": decision.retry_after_ms,
        },
        headers=headers,
    )


def _unavailable_exception() -> HTTPException:
    # Return a stable 503 when rate limit storage is unavailable and fail-closed.
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "RATE_LIMIT_UNAVAILABLE", "message": "Rate limiting unavailable"},
    )


async def enforce_rate_limit(
    *,
    request: Request,
    response: Response,
    principal: PrincipalLike,
    db: AsyncSession,
) -> None:
    # Enforce rate limits after auth resolution with optional fail-open behavior.
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    route_class, cost = route_class_for_request(request)
    limits = _limits_for_route(route_class)
    limiter = _get_rate_limiter()

    try:
        decision = await limiter.check(
            api_key_id=principal.api_key_id,
            tenant_id=principal.tenant_id,
            route_class=route_class,
            cost=cost,
            limits=limits,
        )
    except Exception as exc:  # noqa: BLE001 - guard against Redis connectivity failures
        if settings.rl_fail_mode.lower() == "closed":
            raise _unavailable_exception() from exc
        response.headers["X-RateLimit-Status"] = "degraded"
        if random.random() < _DEGRADED_SAMPLE_RATE:
            request_ctx = get_request_context(request)
            await record_event(
                session=db,
                tenant_id=principal.tenant_id,
                actor_type="system",
                actor_id="rate_limit",
                actor_role=None,
                event_type="system.rate_limit.degraded",
                outcome="failure",
                resource_type="rate_limit",
                request_id=request_ctx["request_id"],
                ip_address=request_ctx["ip_address"],
                user_agent=request_ctx["user_agent"],
                metadata={
                    "route_class": route_class,
                    "path": request.url.path,
                    "fail_mode": settings.rl_fail_mode,
                },
                commit=True,
                best_effort=True,
            )
        logger.warning("rate_limit_degraded path=%s", request.url.path)
        return

    if decision.allowed:
        return

    request_ctx = get_request_context(request)
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="security.rate_limited",
        outcome="failure",
        resource_type="rate_limit",
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "scope": decision.scope,
            "route_class": decision.route_class,
            "retry_after_ms": decision.retry_after_ms,
            "path": request.url.path,
        },
        commit=True,
        best_effort=True,
    )
    raise _throttle_exception(decision=decision)
