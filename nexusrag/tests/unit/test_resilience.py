from __future__ import annotations

import asyncio

import pytest

from nexusrag.services.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    RetryPolicy,
    deterministic_canary,
    retry_async,
)
from nexusrag.core.errors import IntegrationUnavailableError
from nexusrag.services import rollouts
from nexusrag.core.config import get_settings


@pytest.mark.asyncio
async def test_retry_async_retries_transient() -> None:
    calls = {"count": 0}

    async def flaky() -> str:
        calls["count"] += 1
        if calls["count"] < 2:
            raise TimeoutError("timeout")
        return "ok"

    result = await retry_async(
        flaky,
        policy=RetryPolicy(timeout_ms=100, max_attempts=2, backoff_ms=1),
    )
    assert result == "ok"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_circuit_breaker_transitions() -> None:
    now = {"t": 0.0}

    def time_source() -> float:
        return now["t"]

    breaker = CircuitBreaker(
        "test.integration",
        redis=None,
        config=CircuitBreakerConfig(failure_threshold=2, open_seconds=10, half_open_trials=1),
        time_source=time_source,
    )
    await breaker.before_call()
    await breaker.record_failure()
    await breaker.record_failure()
    with pytest.raises(IntegrationUnavailableError):
        await breaker.before_call()

    now["t"] = 11.0
    await breaker.before_call()
    await breaker.record_success()
    await breaker.before_call()


def test_deterministic_canary() -> None:
    tenant_id = "tenant-alpha"
    assert deterministic_canary(tenant_id, 0) is False
    assert deterministic_canary(tenant_id, 100) is True
    assert deterministic_canary(tenant_id, 50) == deterministic_canary(tenant_id, 50)


@pytest.mark.asyncio
async def test_kill_switch_redis_overrides_env(monkeypatch) -> None:
    class StubRedis:
        async def get(self, _key: str):
            return "true"

    async def _stub_redis():
        return StubRedis()

    monkeypatch.setenv("KILL_RUN", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(rollouts, "get_resilience_redis", _stub_redis)
    assert await rollouts.resolve_kill_switch("kill.run") is True
