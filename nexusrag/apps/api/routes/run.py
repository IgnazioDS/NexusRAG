from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from nexusrag.agent.graph import run_graph
from nexusrag.core.config import get_settings
from nexusrag.core.errors import (
    AwsAuthError,
    AwsConfigMissingError,
    AwsRetrievalError,
    DatabaseError,
    IntegrationUnavailableError,
    ProviderConfigError,
    RetrievalConfigError,
    RetrievalError,
    SessionTenantMismatchError,
    ServiceBusyError,
    TTSAuthError,
    TTSConfigMissingError,
    TTSError,
    VertexAuthError,
    VertexRetrievalAuthError,
    VertexRetrievalConfigError,
    VertexRetrievalError,
    VertexTimeoutError,
)
from nexusrag.domain.state import AgentState
from nexusrag.persistence.repos import checkpoints as checkpoints_repo
from nexusrag.persistence.repos import messages as messages_repo
from nexusrag.persistence.repos import sessions as sessions_repo
from nexusrag.providers.llm.factory import get_llm_provider
from nexusrag.providers.retrieval.router import RetrievalRouter
from nexusrag.providers.tts.factory import get_tts_provider
from nexusrag.services.audio.storage import save_audio
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.authz.abac import authorize_corpus_action
from nexusrag.services.costs.budget_guardrails import cost_headers, evaluate_budget_guardrail
from nexusrag.services.costs.metering import estimate_cost, estimate_tokens, record_cost_event
from nexusrag.services.entitlements import (
    FEATURE_COST_CONTROLS,
    FEATURE_COST_VISIBILITY,
    FEATURE_TTS,
    get_effective_entitlements,
    require_feature,
)
from nexusrag.services.operability import get_forced_shed, get_forced_tts_disabled, trigger_runtime_alert
from nexusrag.services.resilience import deterministic_canary, get_run_bulkhead
from nexusrag.services.rollouts import resolve_canary_percentage, resolve_kill_switch
from nexusrag.services.sla.evaluator import evaluate_tenant_sla
from nexusrag.services.sla.signals import record_sla_observation
from nexusrag.services.telemetry import increment_counter, record_segment_timing, record_stream_duration
from nexusrag.apps.api.deps import (
    Principal,
    get_db,
    reject_tenant_id_in_body,
    require_role,
)
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES

logger = logging.getLogger(__name__)
router = APIRouter(tags=["run"], responses=DEFAULT_ERROR_RESPONSES)


class RunRequest(BaseModel):
    session_id: str
    corpus_id: str
    message: str
    top_k: int = Field(default=5, ge=1, le=50)
    audio: bool = False

    # Reject unknown fields so tenant_id cannot be supplied in the payload.
    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "session_id": "sess_123",
                    "corpus_id": "corpus_abc",
                    "message": "Summarize the latest roadmap notes.",
                    "top_k": 5,
                    "audio": False,
                }
            ]
        },
    }


def _wrap_payload(payload_type: str, request_id: str, session_id: str, data: dict) -> dict:
    # Always include request/session identifiers for traceability across streamed events.
    return {
        "type": payload_type,
        "request_id": request_id,
        "session_id": session_id,
        "data": data,
    }


def _sse_message(payload: dict, *, event_name: str = "message", event_id: int | None = None) -> str:
    # SSE framing invariants: emit explicit event names and compact JSON payloads.
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    lines = [f"event: {event_name}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


def _map_error(exc: Exception) -> tuple[str, str]:
    # Map internal exceptions to stable client-facing codes without leaking stack traces.
    if isinstance(exc, ProviderConfigError):
        return "VERTEX_CONFIG_MISSING", str(exc)
    if isinstance(exc, VertexAuthError):
        return "VERTEX_AUTH_ERROR", str(exc)
    if isinstance(exc, VertexTimeoutError):
        return "VERTEX_TIMEOUT", str(exc)
    if isinstance(exc, RetrievalConfigError):
        return "RETRIEVAL_CONFIG_INVALID", str(exc)
    if isinstance(exc, AwsConfigMissingError):
        return "AWS_CONFIG_MISSING", str(exc)
    if isinstance(exc, AwsAuthError):
        return "AWS_AUTH_ERROR", str(exc)
    if isinstance(exc, AwsRetrievalError):
        return "AWS_RETRIEVAL_ERROR", str(exc)
    if isinstance(exc, VertexRetrievalConfigError):
        return "VERTEX_RETRIEVAL_CONFIG_MISSING", str(exc)
    if isinstance(exc, VertexRetrievalAuthError):
        return "VERTEX_RETRIEVAL_AUTH_ERROR", str(exc)
    if isinstance(exc, VertexRetrievalError):
        return "VERTEX_RETRIEVAL_ERROR", str(exc)
    if isinstance(exc, SessionTenantMismatchError):
        return "SESSION_TENANT_MISMATCH", "Session tenant_id does not match."
    if isinstance(exc, IntegrationUnavailableError):
        return "INTEGRATION_UNAVAILABLE", "Integration temporarily unavailable."
    if isinstance(exc, ServiceBusyError):
        return "SERVICE_BUSY", "Service is at capacity; retry shortly."
    if isinstance(exc, RetrievalError):
        return "RETRIEVAL_ERROR", "Retrieval failed."
    if isinstance(exc, (DatabaseError, SQLAlchemyError)):
        return "DB_ERROR", "Database error during run. Check server logs."
    return "UNKNOWN_ERROR", "Internal error during generation."


def _map_tts_error(exc: Exception) -> tuple[str, str]:
    # Keep TTS errors out of the main error channel to avoid confusing core failures.
    if isinstance(exc, TTSConfigMissingError):
        return "TTS_CONFIG_MISSING", str(exc)
    if isinstance(exc, TTSAuthError):
        return "TTS_AUTH_ERROR", str(exc)
    if isinstance(exc, IntegrationUnavailableError):
        return "INTEGRATION_UNAVAILABLE", "TTS temporarily unavailable."
    if isinstance(exc, TTSError):
        return "TTS_ERROR", str(exc)
    return "TTS_ERROR", "TTS request failed."


def _llm_provider_name(settings) -> str:
    # Normalize provider names for cost attribution.
    if settings.llm_provider == "fake":
        return "internal"
    return settings.llm_provider


def _tts_provider_name(settings) -> str:
    # Normalize TTS provider names for cost attribution.
    if settings.tts_provider == "fake":
        return "internal"
    return settings.tts_provider


def _feature_disabled(message: str) -> HTTPException:
    # Return a stable 503 error envelope for disabled features.
    return HTTPException(
        status_code=503,
        detail={"code": "FEATURE_TEMPORARILY_DISABLED", "message": message},
    )


def _sla_headers(*, policy_id: str | None, status_value: str, decision: str, route_class: str, window_end: datetime | None) -> dict[str, str]:
    # Emit stable SLA headers for allow/warn/degrade/shed transparency.
    return {
        "X-SLA-Status": status_value,
        "X-SLA-Policy-Id": policy_id or "",
        "X-SLA-Decision": decision,
        "X-SLA-Route-Class": route_class,
        "X-SLA-Window-End": window_end.isoformat() if window_end else "",
    }


async def _build_shed_stream_response(
    *,
    session: AsyncSession,
    tenant_id: str,
    request_id: str,
    session_id: str,
    run_started: float,
    lease,
    policy_id: str | None,
    status_value: str,
    window_end: datetime | None,
    error_code: str,
    error_message: str,
    sla_headers: dict[str, str],
) -> StreamingResponse:
    # Reuse one shed response path for SLA- and operator-forced load shedding.
    async def shed_stream() -> AsyncGenerator[str, None]:
        seq = 0

        def next_seq() -> int:
            nonlocal seq
            seq += 1
            return seq

        accepted_payload = _wrap_payload(
            "request.accepted",
            request_id,
            session_id,
            {"accepted_at": datetime.now(timezone.utc).isoformat()},
        )
        accepted_payload["seq"] = next_seq()
        yield _sse_message(accepted_payload, event_id=accepted_payload["seq"])

        shed_payload = _wrap_payload(
            "sla.shed",
            request_id,
            session_id,
            {
                "status": status_value,
                "policy_id": policy_id,
                "window_end": window_end.isoformat() if window_end else None,
            },
        )
        shed_payload["seq"] = next_seq()
        yield _sse_message(shed_payload, event_name="sla.shed", event_id=shed_payload["seq"])

        error_payload = _wrap_payload(
            "error",
            request_id,
            session_id,
            {"code": error_code, "message": error_message},
        )
        error_payload["seq"] = next_seq()
        yield _sse_message(error_payload, event_id=error_payload["seq"])

        done_payload = _wrap_payload("done", request_id, session_id, {})
        done_payload["seq"] = next_seq()
        yield _sse_message(done_payload, event_id=done_payload["seq"])

    await _record_sla_observation_safe(
        session=session,
        tenant_id=tenant_id,
        route_class="run",
        latency_ms=(time.monotonic() - run_started) * 1000.0,
        status_code=503,
    )
    return StreamingResponse(
        shed_stream(),
        headers={
            **sla_headers,
            "Cache-Control": "no-cache",
            "Content-Type": "text/event-stream",
            "Connection": "keep-alive",
        },
        media_type="text/event-stream",
        status_code=503,
        background=BackgroundTask(lease.release),
    )


async def _record_sla_observation_safe(
    *,
    session: AsyncSession,
    tenant_id: str,
    route_class: str,
    latency_ms: float,
    status_code: int,
    saturation_pct: float | None = None,
) -> None:
    # Persist SLA measurements best-effort so runtime responses are never blocked.
    settings = get_settings()
    if not settings.sla_engine_enabled:
        return
    try:
        await record_sla_observation(
            session=session,
            tenant_id=tenant_id,
            route_class=route_class,
            latency_ms=latency_ms,
            status_code=status_code,
            saturation_pct=saturation_pct,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - SLA telemetry is advisory, not request-critical
        await session.rollback()
        logger.warning("sla_observation_write_failed tenant=%s route_class=%s", tenant_id, route_class, exc_info=exc)


async def _estimate_run_cost(
    *,
    session: AsyncSession,
    settings,
    retrieval_provider: str | None,
    message: str,
    top_k: int,
    audio: bool,
) -> tuple[Decimal, bool, dict[str, int]]:
    # Estimate run cost deterministically for budget guardrail checks.
    ratio = settings.cost_estimator_token_chars_ratio or 4.0
    input_tokens = estimate_tokens(message, ratio=ratio)
    output_tokens = int(settings.cost_degrade_max_output_tokens or 0)
    token_total = max(0, input_tokens + output_tokens)
    retrieval = await estimate_cost(
        session=session,
        provider=retrieval_provider or "internal",
        component="retrieval",
        rate_type="per_request",
        units={"requests": 1, "top_k": top_k},
    )
    llm = await estimate_cost(
        session=session,
        provider=_llm_provider_name(settings),
        component="llm",
        rate_type="per_1k_tokens",
        units={"tokens": token_total},
    )
    total = retrieval.cost_usd + llm.cost_usd
    if audio:
        tts_chars = max(0, int(output_tokens * ratio))
        tts = await estimate_cost(
            session=session,
            provider=_tts_provider_name(settings),
            component="tts",
            rate_type="per_char",
            units={"chars": tts_chars},
        )
        total += tts.cost_usd
    # Pre-run estimates always rely on heuristics before usage metadata is known.
    return total, True, {"input_tokens": input_tokens, "output_tokens": output_tokens}


async def _record_run_cost_events(
    *,
    session: AsyncSession,
    settings,
    tenant_id: str,
    request_id: str,
    session_id: str,
    message: str,
    answer: str,
    citations: list[dict],
    retrieval_provider: str,
    retrieval_chunks: int,
    top_k: int,
) -> None:
    # Persist best-effort cost events without impacting the response flow.
    if not settings.cost_governance_enabled:
        return
    ratio = settings.cost_estimator_token_chars_ratio or 4.0
    input_tokens = estimate_tokens(message, ratio=ratio)
    output_tokens = estimate_tokens(answer, ratio=ratio)
    try:
        await record_cost_event(
            session=session,
            tenant_id=tenant_id,
            request_id=request_id,
            session_id=session_id,
            route_class="run",
            component="retrieval",
            provider=retrieval_provider,
            units={"requests": 1, "chunks": retrieval_chunks, "top_k": top_k},
            rate_type="per_request",
            metadata={"estimated": True, "chunks": retrieval_chunks},
        )
        await record_cost_event(
            session=session,
            tenant_id=tenant_id,
            request_id=request_id,
            session_id=session_id,
            route_class="run",
            component="llm",
            provider=_llm_provider_name(settings),
            units={"tokens": input_tokens + output_tokens},
            rate_type="per_1k_tokens",
            metadata={
                "estimated": True,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "citations_count": len(citations),
            },
        )
    except Exception as exc:  # noqa: BLE001 - best-effort metering should not fail runs
        logger.warning("cost_metering_run_failed request_id=%s", request_id, exc_info=exc)


@router.post("/run")
async def run(
    payload: RunRequest,
    http_request: Request,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    principal: Principal = Depends(require_role("reader")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # Per-request identifier for tracing a single streamed conversation.
    request_id = str(uuid4())
    run_started = time.monotonic()
    settings = get_settings()
    # Resolve cost entitlements once to avoid redundant entitlement lookups.
    cost_entitlements = await get_effective_entitlements(db, principal.tenant_id)
    cost_controls_enabled = bool(
        cost_entitlements.get(FEATURE_COST_CONTROLS, None)
        and cost_entitlements[FEATURE_COST_CONTROLS].enabled
    )
    cost_visibility_enabled = bool(
        cost_entitlements.get(FEATURE_COST_VISIBILITY, None)
        and cost_entitlements[FEATURE_COST_VISIBILITY].enabled
    )
    # Honor kill switches before allocating run capacity.
    if await resolve_kill_switch("kill.run"):
        raise _feature_disabled("Run is temporarily disabled")
    # Reject resume attempts with an explicit SSE event to guide clients.
    last_event_id = http_request.headers.get("Last-Event-ID")
    if last_event_id:
        async def resume_stream() -> AsyncGenerator[str, None]:
            seq = 0

            def next_seq() -> int:
                nonlocal seq
                seq += 1
                return seq

            resume_payload = {
                "type": "resume.unsupported",
                "request_id": request_id,
                "session_id": payload.session_id,
                "seq": next_seq(),
                "data": {"message": "Resume is not supported; restart the request."},
            }
            yield _sse_message(resume_payload, event_id=resume_payload["seq"])
            done_payload = {
                "type": "done",
                "request_id": request_id,
                "session_id": payload.session_id,
                "seq": next_seq(),
                "data": {},
            }
            yield _sse_message(done_payload, event_id=done_payload["seq"])

        headers = {
            "Cache-Control": "no-cache",
            "Content-Type": "text/event-stream",
            "Connection": "keep-alive",
        }
        return StreamingResponse(resume_stream(), headers=headers, media_type="text/event-stream")
    bulkhead = get_run_bulkhead()
    lease = await bulkhead.acquire()
    if lease is None:
        increment_counter("service_busy_total")
        raise HTTPException(
            status_code=503,
            detail={"code": "SERVICE_BUSY", "message": "Run capacity is saturated"},
            headers={"Retry-After": "1"},
        )

    def _release_and_raise(exc: HTTPException) -> None:
        # Ensure bulkhead capacity is released on early request failures.
        lease.release()
        raise exc
    # Allow operators to force run shedding for incident mitigation workflows.
    if await get_forced_shed(tenant_id=principal.tenant_id, route_class="run"):
        increment_counter("sla_shed_total")
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="sla.enforcement.shed",
            outcome="failure",
            resource_type="run",
            resource_id=request_id,
            request_id=request_id,
            metadata={"policy_id": None, "status": "breached", "forced": True},
            commit=True,
            best_effort=True,
        )
        await trigger_runtime_alert(
            session=db,
            tenant_id=principal.tenant_id,
            source="sla.shed.count",
            severity="critical",
            title="Forced run shedding enabled",
            summary="Operator-forced load shedding blocked /run traffic",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            request_id=request_id,
            details_json={"route_class": "run", "forced": True},
        )
        sla_headers = _sla_headers(
            policy_id=None,
            status_value="breached",
            decision="shed",
            route_class="run",
            window_end=None,
        )
        return await _build_shed_stream_response(
            session=db,
            tenant_id=principal.tenant_id,
            request_id=request_id,
            session_id=payload.session_id,
            run_started=run_started,
            lease=lease,
            policy_id=None,
            status_value="breached",
            window_end=None,
            error_code="SLA_SHED_LOAD",
            error_message="Request shed by operator control",
            sla_headers=sla_headers,
        )
    # Enforce ABAC policies for corpus-scoped run access.
    try:
        await authorize_corpus_action(
            session=db,
            principal=principal,
            corpus_id=payload.corpus_id,
            action="run",
            request=http_request,
        )
    except HTTPException as exc:
        _release_and_raise(exc)
    # Resolve retrieval provider entitlements early to return stable 403s.
    retriever = RetrievalRouter(db)
    resolved_provider: str | None = None
    try:
        provider = await retriever.resolve_provider(principal.tenant_id, payload.corpus_id)
    except RetrievalConfigError:
        # Preserve existing run error behavior when corpus config is invalid.
        pass
    except HTTPException as exc:
        _release_and_raise(exc)
    else:
        resolved_provider = provider
        if provider in {"aws_bedrock_kb", "gcp_vertex"}:
            if await resolve_kill_switch("kill.external_retrieval"):
                _release_and_raise(_feature_disabled("External retrieval is temporarily disabled"))
            rollout_pct = await resolve_canary_percentage("rollout.external_retrieval")
            if not deterministic_canary(principal.tenant_id, rollout_pct):
                _release_and_raise(_feature_disabled("External retrieval is not enabled for this tenant yet"))

    # Evaluate tenant SLA state before budget and generation flows.
    sla_decision = await evaluate_tenant_sla(
        session=db,
        tenant_id=principal.tenant_id,
        route_class="run",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        request=http_request,
        request_id=request_id,
    )
    sla_response_headers = _sla_headers(
        policy_id=sla_decision.policy_id,
        status_value=sla_decision.status,
        decision=sla_decision.enforcement_decision,
        route_class="run",
        window_end=sla_decision.window_end,
    )
    if sla_decision.enforcement_decision == "warn":
        increment_counter("sla_warn_total")
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="sla.enforcement.warned",
            outcome="success",
            resource_type="run",
            resource_id=request_id,
            request_id=request_id,
            metadata={"policy_id": sla_decision.policy_id, "status": sla_decision.status},
            commit=True,
            best_effort=True,
        )
    if sla_decision.enforcement_decision == "shed":
        increment_counter("sla_shed_total")
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="sla.enforcement.shed",
            outcome="failure",
            resource_type="run",
            resource_id=request_id,
            request_id=request_id,
            metadata={"policy_id": sla_decision.policy_id, "status": sla_decision.status},
            commit=True,
            best_effort=True,
        )
        await trigger_runtime_alert(
            session=db,
            tenant_id=principal.tenant_id,
            source="sla.shed.count",
            severity="critical",
            title="Sustained SLA shedding",
            summary="Runtime shed decision triggered from SLA enforcement",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            request_id=request_id,
            details_json={
                "policy_id": sla_decision.policy_id,
                "window_end": sla_decision.window_end.isoformat() if sla_decision.window_end else None,
            },
        )
        return await _build_shed_stream_response(
            session=db,
            tenant_id=principal.tenant_id,
            request_id=request_id,
            session_id=payload.session_id,
            run_started=run_started,
            lease=lease,
            policy_id=sla_decision.policy_id,
            status_value=sla_decision.status,
            window_end=sla_decision.window_end,
            error_code="SLA_SHED_LOAD",
            error_message="Request shed due to sustained SLA breach",
            sla_headers=sla_response_headers,
        )

    budget_decision = None
    effective_top_k = payload.top_k
    effective_audio = payload.audio
    max_output_tokens = None
    effective_retrieval_provider = resolved_provider
    if await get_forced_tts_disabled(tenant_id=principal.tenant_id):
        # Honor operator-level TTS disable overrides before any budget/SLA mitigation.
        effective_audio = False
    if sla_decision.enforcement_decision == "degrade" and sla_decision.degrade_actions is not None:
        increment_counter("sla_degrade_total")
        # Apply SLA-driven mitigation controls before budget enforcement and graph execution.
        effective_audio = not sla_decision.degrade_actions.disable_audio and effective_audio
        effective_top_k = max(1, min(effective_top_k, sla_decision.degrade_actions.top_k_floor))
        max_output_tokens = sla_decision.degrade_actions.max_output_tokens
        if sla_decision.degrade_actions.provider_fallback_order:
            fallback_provider = sla_decision.degrade_actions.provider_fallback_order[0]
            retriever.set_forced_provider(fallback_provider)
            effective_retrieval_provider = fallback_provider
        await record_event(
            session=db,
            tenant_id=principal.tenant_id,
            actor_type="api_key",
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="sla.enforcement.degraded",
            outcome="success",
            resource_type="run",
            resource_id=request_id,
            request_id=request_id,
            metadata={
                "policy_id": sla_decision.policy_id,
                "top_k": effective_top_k,
                "audio_enabled": effective_audio,
                "max_output_tokens": max_output_tokens,
            },
            commit=True,
            best_effort=True,
        )

    # Evaluate budget guardrails before persisting or executing retrieval/generation.
    budget_guardrail_enabled = cost_controls_enabled or cost_visibility_enabled
    estimate_meta: dict[str, int] = {}
    if budget_guardrail_enabled:
        projected_cost, estimated, estimate_meta = await _estimate_run_cost(
            session=db,
            settings=settings,
            retrieval_provider=resolved_provider,
            message=payload.message,
            top_k=payload.top_k,
            audio=payload.audio,
        )
        budget_decision = await evaluate_budget_guardrail(
            session=db,
            tenant_id=principal.tenant_id,
            projected_cost_usd=projected_cost,
            estimated=estimated,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            route_class="run",
            request_id=request_id,
            request=http_request,
            operation="run",
            enforce=cost_controls_enabled,
            raise_on_block=False,
        )
        if budget_decision.degrade_actions:
            increment_counter("cost_degrade_total")
            # Apply degradation strategies before running expensive operations.
            if budget_decision.degrade_actions.top_k:
                effective_top_k = max(1, min(payload.top_k, budget_decision.degrade_actions.top_k))
            if budget_decision.degrade_actions.disable_audio:
                effective_audio = False
            if budget_decision.degrade_actions.max_output_tokens:
                max_output_tokens = budget_decision.degrade_actions.max_output_tokens
            if resolved_provider in {"aws_bedrock_kb", "gcp_vertex"}:
                # Prefer local retrieval during degraded mode to reduce external spend.
                retriever.set_forced_provider("local_pgvector")
                effective_retrieval_provider = "local_pgvector"
        if budget_decision.status == "warn":
            increment_counter("cost_warn_total")
        if not budget_decision.allowed:
            increment_counter("cost_capped_total")
            async def capped_stream() -> AsyncGenerator[str, None]:
                seq = 0

                def next_seq() -> int:
                    nonlocal seq
                    seq += 1
                    return seq

                accepted_payload = _wrap_payload(
                    "request.accepted",
                    request_id,
                    payload.session_id,
                    {"accepted_at": datetime.now(timezone.utc).isoformat()},
                )
                accepted_payload["seq"] = next_seq()
                yield _sse_message(accepted_payload, event_id=accepted_payload["seq"])

                capped_payload = _wrap_payload(
                    "cost.capped",
                    request_id,
                    payload.session_id,
                    {
                        "status": budget_decision.status,
                        "budget_usd": str(budget_decision.budget_usd),
                        "spend_usd": str(budget_decision.spend_usd),
                        "estimated": budget_decision.estimated,
                    },
                )
                capped_payload["seq"] = next_seq()
                yield _sse_message(capped_payload, event_name="cost.capped", event_id=capped_payload["seq"])

                error_payload = _wrap_payload(
                    "error",
                    request_id,
                    payload.session_id,
                    {
                        "code": "COST_BUDGET_EXCEEDED",
                        "message": "Cost budget exceeded",
                    },
                )
                error_payload["seq"] = next_seq()
                yield _sse_message(error_payload, event_id=error_payload["seq"])

                done_payload = _wrap_payload("done", request_id, payload.session_id, {})
                done_payload["seq"] = next_seq()
                yield _sse_message(done_payload, event_id=done_payload["seq"])

            headers = {
                "Cache-Control": "no-cache",
                "Content-Type": "text/event-stream",
                "Connection": "keep-alive",
                **sla_response_headers,
            }
            if cost_visibility_enabled and budget_decision is not None:
                headers.update(cost_headers(budget_decision))
            await _record_sla_observation_safe(
                session=db,
                tenant_id=principal.tenant_id,
                route_class="run",
                latency_ms=(time.monotonic() - run_started) * 1000.0,
                status_code=402,
            )
            return StreamingResponse(
                capped_stream(),
                headers=headers,
                media_type="text/event-stream",
                status_code=402,
                background=BackgroundTask(lease.release),
            )

    # Enforce plan entitlements for optional TTS usage before persistence.
    if effective_audio:
        try:
            await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_TTS)
        except HTTPException as exc:
            _release_and_raise(exc)
        if await resolve_kill_switch("kill.tts"):
            _release_and_raise(_feature_disabled("TTS is temporarily disabled"))
        tts_pct = await resolve_canary_percentage("rollout.tts")
        if not deterministic_canary(principal.tenant_id, tts_pct):
            _release_and_raise(_feature_disabled("TTS is not enabled for this tenant yet"))
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    # TX #1: persist session + user message so history is durable before streaming.
    tx1_started = time.monotonic()
    try:
        await sessions_repo.upsert_session(db, payload.session_id, principal.tenant_id)
        await messages_repo.add_message(db, payload.session_id, "user", payload.message)
        await db.commit()
        if settings.instrumentation_detailed_timers:
            record_segment_timing(
                route_class="run",
                segment="persistence_pre_stream",
                latency_ms=(time.monotonic() - tx1_started) * 1000.0,
            )
    except Exception as exc:
        # Ensure failed transactions do not poison the session state.
        await db.rollback()
        code, message = _map_error(exc)

        async def early_error_stream() -> AsyncGenerator[str, None]:
            # Emit ordered SSE events even when persistence fails before streaming.
            seq = 0

            def next_seq() -> int:
                nonlocal seq
                seq += 1
                return seq
            try:
                accepted_payload = _wrap_payload(
                    "request.accepted",
                    request_id,
                    payload.session_id,
                    {"accepted_at": datetime.now(timezone.utc).isoformat()},
                )
                accepted_payload["seq"] = next_seq()
                yield _sse_message(accepted_payload, event_id=accepted_payload["seq"])

                error_payload = _wrap_payload(
                    "error",
                    request_id,
                    payload.session_id,
                    {"code": code, "message": message},
                )
                error_payload["seq"] = next_seq()
                yield _sse_message(error_payload, event_id=error_payload["seq"])

                done_payload = _wrap_payload("done", request_id, payload.session_id, {})
                done_payload["seq"] = next_seq()
                yield _sse_message(done_payload, event_id=done_payload["seq"])
            finally:
                lease.release()

        headers = {
            "Cache-Control": "no-cache",
            "Content-Type": "text/event-stream",
            "Connection": "keep-alive",
        }
        return StreamingResponse(
            early_error_stream(),
            headers=headers,
            media_type="text/event-stream",
            background=BackgroundTask(lease.release),
        )

    request_ctx = get_request_context(http_request)
    # Record the run invocation after persistence succeeds to avoid logging failed writes.
    await record_event(
        session=db,
        tenant_id=principal.tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="run.invoked",
        outcome="success",
        resource_type="run",
        resource_id=request_id,
        request_id=request_id,
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={
            "session_id": payload.session_id,
            "corpus_id": payload.corpus_id,
            "top_k_requested": payload.top_k,
            "top_k_effective": effective_top_k,
            "audio_requested": payload.audio,
            "audio_effective": effective_audio,
            "cost_status": budget_decision.status if budget_decision else "ok",
        },
        commit=True,
        best_effort=True,
    )

    # Use a shared queue for token and debug events to preserve stream order.
    queue: asyncio.Queue[dict] = asyncio.Queue()
    done = asyncio.Event()
    final_state: AgentState | None = None
    error: Exception | None = None
    disconnect_event = asyncio.Event()
    # Thread-safe cancel signal so the blocking Vertex stream can exit promptly.
    cancel_event = threading.Event()
    # Reuse the request-scoped retriever/LLM to avoid extra connections.
    llm = get_llm_provider(request_id=request_id, cancel_event=cancel_event)
    retrieval_provider_name = effective_retrieval_provider or "internal"
    retrieval_chunks = 0

    loop = asyncio.get_running_loop()

    def token_callback(delta: str) -> None:
        # Drop tokens once the client disconnects to avoid buffering unused output.
        if disconnect_event.is_set():
            return
        loop.call_soon_threadsafe(queue.put_nowait, {"kind": "token", "delta": delta})

    def retrieval_callback(provider: str, num_chunks: int) -> None:
        # Emit optional debug events only when explicitly enabled.
        nonlocal retrieval_provider_name, retrieval_chunks
        retrieval_provider_name = provider
        retrieval_chunks = num_chunks
        if not settings.debug_events:
            return
        queue.put_nowait(
            {
                "kind": "event",
                "payload": _wrap_payload(
                    "debug.retrieval",
                    request_id,
                    payload.session_id,
                    {"provider": provider, "num_chunks": num_chunks},
                ),
            }
        )

    async def run_agent() -> None:
        nonlocal final_state, error
        try:
            state: AgentState = {
                "session_id": payload.session_id,
                "tenant_id": principal.tenant_id,
                "corpus_id": payload.corpus_id,
                "user_message": payload.message,
                "history": [],
                "retrieved": [],
                "answer": None,
                "citations": [],
                "checkpoint_state": None,
                "timings_ms": {},
            }
            final_state = await run_graph(
                retriever=retriever,
                llm=llm,
                session=db,
                state=state,
                top_k=effective_top_k,
                token_callback=token_callback,
                retrieval_callback=retrieval_callback,
                max_output_tokens=max_output_tokens,
                token_estimator_ratio=settings.cost_estimator_token_chars_ratio,
            )
        except asyncio.CancelledError:
            # Allow cancellation to propagate so disconnects stop streaming quickly.
            raise
        except Exception as exc:
            error = exc
            logger.exception("run_graph failed")
        finally:
            done.set()

    async def event_stream() -> AsyncGenerator[str, None]:
        seq = 0
        heartbeat_interval = max(1, int(settings.run_sse_heartbeat_s))
        flush_interval_s = max(0.0, int(settings.sse_flush_interval_ms) / 1000.0)
        last_emit = time.monotonic()
        stream_start = time.monotonic()
        first_token_emitted = False
        logical_status_code = 200

        def next_seq() -> int:
            # Monotonic sequence numbers help clients reconcile stream ordering.
            nonlocal seq
            seq += 1
            return seq

        def emit(payload: dict, *, event_name: str = "message") -> str:
            # Attach sequence numbers to every event payload before streaming.
            nonlocal last_emit
            payload["seq"] = next_seq()
            last_emit = time.monotonic()
            return _sse_message(payload, event_name=event_name, event_id=payload["seq"])

        accepted_payload = _wrap_payload(
            "request.accepted",
            request_id,
            payload.session_id,
            {"accepted_at": datetime.now(timezone.utc).isoformat()},
        )
        yield emit(accepted_payload)
        if sla_decision.enforcement_decision in {"warn", "degrade"}:
            sla_event_name = "sla.warn" if sla_decision.enforcement_decision == "warn" else "sla.degrade.applied"
            sla_payload = _wrap_payload(
                sla_event_name,
                request_id,
                payload.session_id,
                {
                    "status": sla_decision.status,
                    "policy_id": sla_decision.policy_id,
                    "decision": sla_decision.enforcement_decision,
                    "window_end": sla_decision.window_end.isoformat() if sla_decision.window_end else None,
                    "recommended_actions": list(sla_decision.recommended_actions),
                    "degrade_actions": sla_decision.degrade_actions.__dict__
                    if sla_decision.degrade_actions
                    else {},
                },
            )
            yield emit(sla_payload, event_name=sla_event_name)
        if budget_decision and budget_decision.status in {"warn", "degraded"}:
            event_name = "cost.warn" if budget_decision.status == "warn" else "cost.degraded"
            cost_payload = _wrap_payload(
                event_name,
                request_id,
                payload.session_id,
                {
                    "status": budget_decision.status,
                    "budget_usd": str(budget_decision.budget_usd),
                    "spend_usd": str(budget_decision.spend_usd),
                    "remaining_usd": str(budget_decision.remaining_usd)
                    if budget_decision.remaining_usd is not None
                    else None,
                    "estimated": budget_decision.estimated,
                    "estimate_meta": estimate_meta,
                    "degrade_actions": budget_decision.degrade_actions.__dict__
                    if budget_decision.degrade_actions
                    else {},
                },
            )
            yield emit(cost_payload, event_name=event_name)
        task = asyncio.create_task(run_agent())
        try:
            while not done.is_set() or not queue.empty():
                if await http_request.is_disconnected():
                    # Stop streaming immediately when the client disconnects.
                    disconnect_event.set()
                    cancel_event.set()
                    increment_counter("sse_streams_disconnected")
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    now = time.monotonic()
                    if now - last_emit >= heartbeat_interval:
                        heartbeat_payload = {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "request_id": request_id,
                        }
                        yield _sse_message(
                            {**heartbeat_payload, "seq": next_seq()},
                            event_name="heartbeat",
                            event_id=seq,
                        )
                        if flush_interval_s > 0:
                            await asyncio.sleep(flush_interval_s)
                        last_emit = now
                    continue
                if item.get("kind") == "event":
                    # Send debug events as fully-formed SSE payloads.
                    yield emit(item["payload"])
                    if flush_interval_s > 0:
                        await asyncio.sleep(flush_interval_s)
                    continue
                # Stream each delta as its own SSE message to avoid buffering output.
                delta = item.get("delta")
                if not isinstance(delta, str):
                    continue
                if not first_token_emitted:
                    first_token_emitted = True
                    if settings.instrumentation_detailed_timers:
                        record_segment_timing(
                            route_class="run",
                            segment="sse_first_token",
                            latency_ms=(time.monotonic() - stream_start) * 1000.0,
                        )
                yield emit(
                    _wrap_payload(
                        "token.delta",
                        request_id,
                        payload.session_id,
                        {"delta": delta},
                    )
                )
                if flush_interval_s > 0:
                    await asyncio.sleep(flush_interval_s)

            if disconnect_event.is_set():
                # Do not emit final/error events after a client disconnects.
                return

            await task

            if error:
                code, message = _map_error(error)
                logical_status_code = 500
                yield emit(
                    _wrap_payload(
                        "error",
                        request_id,
                        payload.session_id,
                        {"code": code, "message": message},
                    )
                )
                yield emit(
                    _wrap_payload("done", request_id, payload.session_id, {})
                )
                return

            assert final_state is not None
            answer = final_state.get("answer") or ""
            citations = final_state.get("citations", [])
            checkpoint_state = final_state.get("checkpoint_state") or {}
            graph_timings = final_state.get("timings_ms") or {}
            if settings.instrumentation_detailed_timers:
                segment_map = {
                    "history_load": "persistence_history_read",
                    "retrieval": "retrieval",
                    "generation": "generation_stream",
                    "checkpoint_snapshot": "checkpoint_snapshot",
                }
                for source_key, segment_name in segment_map.items():
                    timing_value = graph_timings.get(source_key)
                    if timing_value is None:
                        continue
                    record_segment_timing(
                        route_class="run",
                        segment=segment_name,
                        latency_ms=float(timing_value),
                    )

            try:
                # TX #2: persist assistant + checkpoint only after a successful run.
                tx2_started = time.monotonic()
                await messages_repo.add_message(db, payload.session_id, "assistant", answer)
                await checkpoints_repo.add_checkpoint(db, payload.session_id, checkpoint_state)
                await db.commit()
                if settings.instrumentation_detailed_timers:
                    record_segment_timing(
                        route_class="run",
                        segment="persistence_post_stream",
                        latency_ms=(time.monotonic() - tx2_started) * 1000.0,
                    )
            except Exception as exc:
                # Roll back to avoid partial writes if post-run persistence fails.
                await db.rollback()
                code, message = _map_error(exc)
                logical_status_code = 500
                yield _sse_message(
                    _wrap_payload(
                        "error",
                        request_id,
                        payload.session_id,
                        {"code": code, "message": message},
                    )
                )
                return

            yield emit(
                _wrap_payload(
                    "message.final",
                    request_id,
                    payload.session_id,
                    {"text": answer, "citations": citations},
                )
            )

            await _record_run_cost_events(
                session=db,
                settings=settings,
                tenant_id=principal.tenant_id,
                request_id=request_id,
                session_id=payload.session_id,
                message=payload.message,
                answer=answer,
                citations=citations,
                retrieval_provider=retrieval_provider_name,
                retrieval_chunks=retrieval_chunks,
                top_k=effective_top_k,
            )

            if not effective_audio:
                yield emit(_wrap_payload("done", request_id, payload.session_id, {}))
                return
            if await http_request.is_disconnected():
                # Skip TTS if the client disconnects after the text response.
                return
            try:
                tts_started = time.monotonic()
                tts = get_tts_provider()
                audio_bytes = await tts.synthesize(answer)
                audio_id, _path, audio_url = await save_audio(
                    session=db,
                    tenant_id=principal.tenant_id,
                    audio_bytes=audio_bytes,
                    base_url=settings.audio_base_url,
                )
                try:
                    await record_cost_event(
                        session=db,
                        tenant_id=principal.tenant_id,
                        request_id=request_id,
                        session_id=payload.session_id,
                        route_class="run",
                        component="tts",
                        provider=_tts_provider_name(settings),
                        units={"chars": len(answer)},
                        rate_type="per_char",
                        metadata={"estimated": True},
                    )
                except Exception as exc:  # noqa: BLE001 - best-effort metering should not fail runs
                    logger.warning("cost_metering_tts_failed request_id=%s", request_id, exc_info=exc)
                if settings.instrumentation_detailed_timers:
                    record_segment_timing(
                        route_class="run",
                        segment="tts",
                        latency_ms=(time.monotonic() - tts_started) * 1000.0,
                    )
                yield emit(
                    _wrap_payload(
                        "audio.ready",
                        request_id,
                        payload.session_id,
                        {"audio_url": audio_url, "audio_id": audio_id, "mime": "audio/mpeg"},
                    )
                )
            except Exception as exc:
                code, message = _map_tts_error(exc)
                yield emit(
                    _wrap_payload(
                        "audio.error",
                        request_id,
                        payload.session_id,
                        {"code": code, "message": message},
                    )
                )
            yield emit(_wrap_payload("done", request_id, payload.session_id, {}))
        finally:
            if not task.done():
                task.cancel()
            increment_counter("sse_streams_completed")
            stream_duration_ms = (time.monotonic() - stream_start) * 1000.0
            record_stream_duration(stream_duration_ms)
            if settings.instrumentation_detailed_timers:
                record_segment_timing(
                    route_class="run",
                    segment="sse_completion",
                    latency_ms=stream_duration_ms,
                )
            await _record_sla_observation_safe(
                session=db,
                tenant_id=principal.tenant_id,
                route_class="run",
                latency_ms=(time.monotonic() - run_started) * 1000.0,
                status_code=logical_status_code,
            )

    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
        **sla_response_headers,
    }
    if cost_visibility_enabled and budget_decision is not None:
        headers.update(cost_headers(budget_decision))
    return StreamingResponse(
        event_stream(),
        headers=headers,
        media_type="text/event-stream",
        background=BackgroundTask(lease.release),
    )
