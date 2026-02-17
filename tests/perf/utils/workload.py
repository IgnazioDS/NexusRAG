from __future__ import annotations

import asyncio
import json
import logging
import os
import resource
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from nexusrag.apps.api import rate_limit
from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Corpus
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.entitlements import reset_entitlements_cache
from nexusrag.services.resilience import reset_bulkheads
from nexusrag.tests.utils.auth import create_test_api_key


@dataclass(frozen=True)
class TenantContext:
    # Keep tenant fixture data together for deterministic scenario setup.
    tenant_id: str
    tier: str
    reader_headers: dict[str, str]
    admin_headers: dict[str, str]
    corpus_id: str


@dataclass(frozen=True)
class RequestRecord:
    # Capture normalized request outcomes for cross-scenario aggregation.
    scenario: str
    tenant_id: str
    tier: str
    route_class: str
    method: str
    path: str
    status_code: int
    latency_ms: float
    timeout: bool
    error_code: str | None
    degraded: bool
    shed: bool
    rate_limited: bool
    quota_exceeded: bool


@dataclass(frozen=True)
class StreamRecord:
    # Track SSE-specific latencies and disconnect behavior.
    scenario: str
    tenant_id: str
    tier: str
    first_token_latency_ms: float | None
    completion_latency_ms: float
    disconnected: bool


def perf_report_dir() -> Path:
    # Resolve report output location from env for reproducible artifact paths.
    settings = get_settings()
    return Path(settings.perf_report_dir)


def memory_usage_mb() -> float:
    # Use max RSS as a portable approximation for process memory footprint.
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # macOS reports bytes while Linux reports KiB; normalize by platform-like magnitude.
    if usage.ru_maxrss > 10_000_000:
        return float(usage.ru_maxrss) / (1024.0 * 1024.0)
    return float(usage.ru_maxrss) / 1024.0


def configure_perf_environment(*, deterministic: bool) -> None:
    # Force deterministic provider/runtime knobs before creating ASGI app instances.
    if deterministic:
        os.environ["LLM_PROVIDER"] = "fake"
        os.environ["TTS_PROVIDER"] = "fake"
        os.environ["COST_GOVERNANCE_ENABLED"] = "true"
        os.environ["PERF_FAKE_PROVIDER_MODE"] = "true"
        os.environ["INGEST_EXECUTION_MODE"] = "inline"
        # Remove policy throttles so deterministic perf gates measure runtime behavior, not guardrail denials.
        os.environ["RATE_LIMIT_ENABLED"] = "false"
        os.environ.setdefault("RUN_BULKHEAD_MAX_CONCURRENCY", "12")
        os.environ.setdefault("INGEST_BULKHEAD_MAX_CONCURRENCY", "6")
    get_settings.cache_clear()
    # Keep perf command output compact; verbose per-request logs hide actionable gate failures.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    reset_entitlements_cache()
    rate_limit.reset_rate_limiter_state()
    reset_bulkheads()


async def load_fixture_tenants(path: Path) -> list[dict[str, Any]]:
    # Parse fixture JSON once so scenarios share the same tenant tiers/plans.
    return json.loads(path.read_text(encoding="utf-8"))


async def seed_corpus(*, tenant_id: str, name: str) -> str:
    # Seed corpus rows directly to avoid extra API overhead in hot-path tests.
    corpus_id = f"c-perf-{uuid4().hex}"
    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id=tenant_id,
                name=name,
                provider_config_json={"retrieval": {"provider": "local_pgvector", "top_k_default": 5}},
            )
        )
        await session.commit()
    return corpus_id


async def bootstrap_tenants(*, fixture_path: Path, scenario_name: str) -> list[TenantContext]:
    # Provision deterministic tenant keys/corpora for each scenario run.
    fixture_rows = await load_fixture_tenants(fixture_path)
    contexts: list[TenantContext] = []
    for row in fixture_rows:
        tenant_id = f"perf-{scenario_name}-{row['name']}-{uuid4().hex[:8]}"
        plan_id = str(row.get("plan_id") or "enterprise")
        _raw_reader, reader_headers, _reader_user_id, _reader_key_id = await create_test_api_key(
            tenant_id=tenant_id,
            role="reader",
            plan_id=plan_id,
        )
        _raw_admin, admin_headers, _admin_user_id, _admin_key_id = await create_test_api_key(
            tenant_id=tenant_id,
            role="admin",
            plan_id=plan_id,
        )
        corpus_id = await seed_corpus(tenant_id=tenant_id, name=f"Perf {row['name']}")
        contexts.append(
            TenantContext(
                tenant_id=tenant_id,
                tier=str(row["tier"]),
                reader_headers=reader_headers,
                admin_headers=admin_headers,
                corpus_id=corpus_id,
            )
        )
    return contexts


def make_client() -> AsyncClient:
    # Use ASGI in-process transport for reproducible deterministic perf execution.
    app = create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://perf")


async def run_with_concurrency(
    *,
    workers: int,
    jobs: list[Callable[[], Awaitable[Any]]],
) -> list[Any]:
    # Bound concurrent workers so scenario pressure is explicit and repeatable.
    semaphore = asyncio.Semaphore(max(1, workers))

    async def _run_job(job: Callable[[], Awaitable[Any]]) -> Any:
        async with semaphore:
            return await job()

    tasks = [asyncio.create_task(_run_job(job)) for job in jobs]
    return await asyncio.gather(*tasks)


async def execute_request(
    *,
    client: AsyncClient,
    scenario: str,
    tenant: TenantContext,
    method: str,
    path: str,
    route_class: str,
    json_payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_s: float = 30.0,
) -> RequestRecord:
    # Normalize sync JSON request metrics into a single record shape.
    started = time.monotonic()
    error_code: str | None = None
    status_code = 599
    timeout = False
    degraded = False
    shed = False
    rate_limited = False
    quota_exceeded = False
    try:
        response = await client.request(
            method,
            path,
            json=json_payload,
            headers=headers,
            timeout=timeout_s,
        )
        status_code = int(response.status_code)
        degraded = response.headers.get("X-Cost-Status") in {"degraded", "capped"} or response.headers.get(
            "X-SLA-Decision"
        ) == "degrade"
        try:
            payload = response.json()
            error_code = (payload.get("error") or {}).get("code") if isinstance(payload, dict) else None
        except Exception:
            error_code = None
        shed = error_code == "SLA_SHED_LOAD"
        rate_limited = error_code == "RATE_LIMITED"
        quota_exceeded = error_code in {"QUOTA_EXCEEDED", "COST_BUDGET_EXCEEDED"}
    except TimeoutError:
        timeout = True
    except Exception:
        status_code = 599
    latency_ms = (time.monotonic() - started) * 1000.0
    return RequestRecord(
        scenario=scenario,
        tenant_id=tenant.tenant_id,
        tier=tenant.tier,
        route_class=route_class,
        method=method,
        path=path,
        status_code=status_code,
        latency_ms=latency_ms,
        timeout=timeout,
        error_code=error_code,
        degraded=degraded,
        shed=shed,
        rate_limited=rate_limited,
        quota_exceeded=quota_exceeded,
    )


async def execute_run_stream(
    *,
    client: AsyncClient,
    scenario: str,
    tenant: TenantContext,
    message: str,
    top_k: int,
    audio: bool,
    timeout_s: float = 60.0,
) -> tuple[RequestRecord, StreamRecord]:
    # Capture SSE first-token and completion latencies for /v1/run behavior.
    started = time.monotonic()
    first_token_latency_ms: float | None = None
    completion_latency_ms = 0.0
    status_code = 599
    timeout = False
    error_code: str | None = None
    degraded = False
    shed = False
    rate_limited = False
    quota_exceeded = False
    disconnected = False
    try:
        async with client.stream(
            "POST",
            "/v1/run",
            headers=tenant.reader_headers,
            json={
                "session_id": f"s-perf-{uuid4().hex}",
                "corpus_id": tenant.corpus_id,
                "message": message,
                "top_k": top_k,
                "audio": audio,
            },
            timeout=timeout_s,
        ) as response:
            status_code = int(response.status_code)
            degraded = response.headers.get("X-SLA-Decision") == "degrade" or response.headers.get("X-Cost-Status") in {
                "degraded",
                "capped",
            }
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                payload_type = payload.get("type")
                if payload_type == "token.delta" and first_token_latency_ms is None:
                    first_token_latency_ms = (time.monotonic() - started) * 1000.0
                if payload_type == "error":
                    error_data = payload.get("data") or {}
                    if isinstance(error_data, dict):
                        error_code = str(error_data.get("code") or "UNKNOWN_ERROR")
                        shed = error_code == "SLA_SHED_LOAD"
                        rate_limited = error_code == "RATE_LIMITED"
                        quota_exceeded = error_code in {"QUOTA_EXCEEDED", "COST_BUDGET_EXCEEDED"}
                if payload_type == "done":
                    break
    except TimeoutError:
        timeout = True
    except Exception:
        disconnected = True
    completion_latency_ms = (time.monotonic() - started) * 1000.0
    record = RequestRecord(
        scenario=scenario,
        tenant_id=tenant.tenant_id,
        tier=tenant.tier,
        route_class="run",
        method="POST",
        path="/v1/run",
        status_code=status_code,
        latency_ms=completion_latency_ms,
        timeout=timeout,
        error_code=error_code,
        degraded=degraded,
        shed=shed,
        rate_limited=rate_limited,
        quota_exceeded=quota_exceeded,
    )
    stream = StreamRecord(
        scenario=scenario,
        tenant_id=tenant.tenant_id,
        tier=tenant.tier,
        first_token_latency_ms=first_token_latency_ms,
        completion_latency_ms=completion_latency_ms,
        disconnected=disconnected,
    )
    return record, stream
