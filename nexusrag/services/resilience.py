from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from redis.asyncio import Redis

from nexusrag.core.config import get_settings
from nexusrag.core.errors import IntegrationUnavailableError
from nexusrag.services.telemetry import increment_counter, set_gauge


logger = logging.getLogger(__name__)


TransientException = (TimeoutError, OSError)


_redis_pool: Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None
_redis_lock = asyncio.Lock()


async def get_resilience_redis() -> Redis | None:
    # Reuse a shared Redis connection for breaker/rollout coordination.
    settings = get_settings()
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    global _redis_pool, _redis_loop
    if _redis_pool is not None and _redis_loop == current_loop:
        return _redis_pool
    if _redis_pool is not None and _redis_loop != current_loop:
        _redis_pool = None
    async with _redis_lock:
        if _redis_pool is None:
            try:
                _redis_pool = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
                _redis_loop = current_loop
            except Exception as exc:  # noqa: BLE001 - Redis might be unavailable in dev
                logger.warning("resilience_redis_unavailable", exc_info=exc)
                return None
    return _redis_pool


def _default_retryable(exc: Exception) -> bool:
    # Retry only transient network/timeout failures by default.
    if isinstance(exc, TransientException):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status >= 500:
        return True
    return False


@dataclass(frozen=True)
class RetryPolicy:
    # Centralize external retry behavior for deterministic policy changes.
    timeout_ms: int
    max_attempts: int
    backoff_ms: int


def default_retry_policy() -> RetryPolicy:
    settings = get_settings()
    return RetryPolicy(
        timeout_ms=settings.ext_call_timeout_ms,
        max_attempts=settings.ext_retry_max_attempts,
        backoff_ms=settings.ext_retry_backoff_ms,
    )


async def retry_async(
    func: Callable[[], Awaitable[Any]],
    *,
    policy: RetryPolicy | None = None,
    retryable: Callable[[Exception], bool] | None = None,
) -> Any:
    # Retry helper with jittered backoff for transient failures only.
    policy = policy or default_retry_policy()
    retryable = retryable or _default_retryable
    attempt = 1
    while True:
        try:
            return await asyncio.wait_for(func(), timeout=policy.timeout_ms / 1000.0)
        except Exception as exc:  # noqa: BLE001 - caller handles non-transient failures
            if attempt >= max(policy.max_attempts, 1) or not retryable(exc):
                raise
            # Track retry volume so operators can detect retry storms.
            increment_counter("external_retries_total")
            jitter = random.uniform(0.5, 1.5)
            sleep_s = (policy.backoff_ms / 1000.0) * (2 ** (attempt - 1)) * jitter
            await asyncio.sleep(sleep_s)
            attempt += 1


@dataclass(frozen=True)
class CircuitBreakerConfig:
    # Store thresholds in settings so operators can tune without code changes.
    failure_threshold: int
    open_seconds: int
    half_open_trials: int


@dataclass
class CircuitBreakerState:
    # Track failures and transitions across instances via Redis.
    state: str
    failures: int
    opened_at: float | None
    half_open_trials: int


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        redis: Redis | None = None,
        config: CircuitBreakerConfig | None = None,
        time_source: Callable[[], float] | None = None,
        on_transition: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._name = name
        self._redis = redis
        self._config = config or CircuitBreakerConfig(
            failure_threshold=get_settings().cb_failure_threshold,
            open_seconds=get_settings().cb_open_seconds,
            half_open_trials=get_settings().cb_half_open_trials,
        )
        self._time = time_source or time.monotonic
        self._on_transition = on_transition
        self._local_state = CircuitBreakerState("closed", 0, None, 0)

    @property
    def name(self) -> str:
        return self._name

    def _key(self) -> str:
        return f"{get_settings().cb_redis_prefix}:{self._name}"

    async def _load(self) -> CircuitBreakerState:
        # Read breaker state from Redis when available; otherwise fall back to local.
        if self._redis is None:
            return self._local_state
        raw = await self._redis.hgetall(self._key())
        if not raw:
            return self._local_state
        state = raw.get("state", "closed")
        failures = int(raw.get("failures", 0))
        opened_at = float(raw["opened_at"]) if raw.get("opened_at") else None
        half_open_trials = int(raw.get("half_open_trials", 0))
        return CircuitBreakerState(state, failures, opened_at, half_open_trials)

    async def _save(self, state: CircuitBreakerState) -> None:
        # Persist breaker state in Redis to share across instances.
        if self._redis is None:
            self._local_state = state
            return
        payload = {
            "state": state.state,
            "failures": str(state.failures),
            "opened_at": str(state.opened_at or ""),
            "half_open_trials": str(state.half_open_trials),
        }
        await self._redis.hset(self._key(), mapping=payload)
        ttl = max(self._config.open_seconds * 4, 60)
        await self._redis.expire(self._key(), ttl)

    async def _transition(self, state: CircuitBreakerState, target: str) -> CircuitBreakerState:
        # Emit logs on state transitions for operator visibility.
        if state.state != target:
            logger.warning("circuit_breaker_transition name=%s from=%s to=%s", self._name, state.state, target)
            increment_counter(f"circuit_breaker_transition_total.{self._name}.{target}")
            if target == "open":
                increment_counter("circuit_breaker_open_total")
            state_value = {"closed": 0.0, "half_open": 0.5, "open": 1.0}.get(target, 0.0)
            set_gauge(f"circuit_breaker_state.{self._name}", state_value)
            if self._on_transition is not None:
                await self._on_transition(self._name, target)
        return CircuitBreakerState(target, 0, self._time() if target == "open" else None, 0)

    async def before_call(self) -> CircuitBreakerState:
        # Decide whether calls are allowed and update half-open counters.
        state = await self._load()
        now = self._time()
        if state.state == "open":
            if state.opened_at is not None and (now - state.opened_at) >= self._config.open_seconds:
                state = await self._transition(state, "half_open")
                await self._save(state)
            else:
                raise IntegrationUnavailableError(f"{self._name} is temporarily unavailable")
        if state.state == "half_open":
            if state.half_open_trials >= self._config.half_open_trials:
                raise IntegrationUnavailableError(f"{self._name} is temporarily unavailable")
            state.half_open_trials += 1
            await self._save(state)
        return state

    async def record_success(self) -> None:
        state = await self._load()
        if state.state != "closed":
            state = await self._transition(state, "closed")
        else:
            state.failures = 0
            state.half_open_trials = 0
        await self._save(state)

    async def record_failure(self) -> None:
        state = await self._load()
        if state.state == "half_open":
            state = await self._transition(state, "open")
            await self._save(state)
            return
        failures = state.failures + 1
        if failures >= self._config.failure_threshold:
            state = await self._transition(state, "open")
        else:
            state.failures = failures
        await self._save(state)


@dataclass
class BulkheadLease:
    # Track bulkhead ownership to avoid double-releasing.
    semaphore: asyncio.Semaphore
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.semaphore.release()
        self.released = True


class Bulkhead:
    def __init__(self, name: str, limit: int) -> None:
        # Use asyncio semaphores to cap concurrency for expensive operations.
        self._name = name
        self._limit = max(1, limit)
        self._sem = asyncio.Semaphore(self._limit)

    @property
    def name(self) -> str:
        return self._name

    @property
    def limit(self) -> int:
        return self._limit

    async def acquire(self) -> BulkheadLease | None:
        # Attempt to acquire immediately; return None if saturated.
        if self._sem.locked():
            return None
        await self._sem.acquire()
        return BulkheadLease(self._sem)

    def release(self) -> None:
        # Preserve legacy release hooks for callers that don't use leases.
        self._sem.release()


_run_bulkhead: Bulkhead | None = None
_ingest_bulkhead: Bulkhead | None = None


def get_run_bulkhead() -> Bulkhead:
    # Initialize the /run concurrency bulkhead from settings.
    global _run_bulkhead
    if _run_bulkhead is None:
        settings = get_settings()
        _run_bulkhead = Bulkhead(
            "run",
            settings.run_bulkhead_max_concurrency or settings.run_max_concurrency,
        )
    return _run_bulkhead


def get_ingest_bulkhead() -> Bulkhead:
    # Initialize ingestion worker bulkhead from settings.
    global _ingest_bulkhead
    if _ingest_bulkhead is None:
        settings = get_settings()
        _ingest_bulkhead = Bulkhead(
            "ingest",
            settings.ingest_bulkhead_max_concurrency or settings.ingest_max_concurrency,
        )
    return _ingest_bulkhead


def reset_bulkheads() -> None:
    # Allow tests to reset bulkhead limits after tweaking settings.
    global _run_bulkhead, _ingest_bulkhead
    _run_bulkhead = None
    _ingest_bulkhead = None


def deterministic_canary(tenant_id: str, percentage: int) -> bool:
    # Deterministically assign tenants based on stable hash percentage.
    percentage = max(0, min(int(percentage), 100))
    if percentage == 0:
        return False
    if percentage == 100:
        return True
    digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < percentage


async def get_circuit_breaker_state(name: str) -> str:
    # Fetch circuit breaker state from Redis for ops reporting.
    redis = await get_resilience_redis()
    if redis is None:
        return "unknown"
    raw = await redis.hgetall(f"{get_settings().cb_redis_prefix}:{name}")
    if not raw:
        return "closed"
    return raw.get("state", "closed")
