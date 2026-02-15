from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
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
from nexusrag.services.entitlements import FEATURE_TTS, require_feature
from nexusrag.services.resilience import deterministic_canary, get_run_bulkhead
from nexusrag.services.rollouts import resolve_canary_percentage, resolve_kill_switch
from nexusrag.services.telemetry import increment_counter, record_stream_duration
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


def _feature_disabled(message: str) -> HTTPException:
    # Return a stable 503 error envelope for disabled features.
    return HTTPException(
        status_code=503,
        detail={"code": "FEATURE_TEMPORARILY_DISABLED", "message": message},
    )


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
    # Enforce plan entitlements for optional TTS usage before persistence.
    if payload.audio:
        try:
            await require_feature(session=db, tenant_id=principal.tenant_id, feature_key=FEATURE_TTS)
        except HTTPException as exc:
            _release_and_raise(exc)
        if await resolve_kill_switch("kill.tts"):
            _release_and_raise(_feature_disabled("TTS is temporarily disabled"))
        tts_pct = await resolve_canary_percentage("rollout.tts")
        if not deterministic_canary(principal.tenant_id, tts_pct):
            _release_and_raise(_feature_disabled("TTS is not enabled for this tenant yet"))
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
    try:
        provider = await retriever.resolve_provider(principal.tenant_id, payload.corpus_id)
    except RetrievalConfigError:
        # Preserve existing run error behavior when corpus config is invalid.
        pass
    except HTTPException as exc:
        _release_and_raise(exc)
    else:
        if provider in {"aws_bedrock_kb", "gcp_vertex"}:
            if await resolve_kill_switch("kill.external_retrieval"):
                _release_and_raise(_feature_disabled("External retrieval is temporarily disabled"))
            rollout_pct = await resolve_canary_percentage("rollout.external_retrieval")
            if not deterministic_canary(principal.tenant_id, rollout_pct):
                _release_and_raise(_feature_disabled("External retrieval is not enabled for this tenant yet"))
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    # TX #1: persist session + user message so history is durable before streaming.
    try:
        await sessions_repo.upsert_session(db, payload.session_id, principal.tenant_id)
        await messages_repo.add_message(db, payload.session_id, "user", payload.message)
        await db.commit()
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
            "top_k": payload.top_k,
            "audio": payload.audio,
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

    loop = asyncio.get_running_loop()

    def token_callback(delta: str) -> None:
        # Drop tokens once the client disconnects to avoid buffering unused output.
        if disconnect_event.is_set():
            return
        loop.call_soon_threadsafe(queue.put_nowait, {"kind": "token", "delta": delta})

    settings = get_settings()

    def retrieval_callback(provider: str, num_chunks: int) -> None:
        # Emit optional debug events only when explicitly enabled.
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
            }
            final_state = await run_graph(
                retriever=retriever,
                llm=llm,
                session=db,
                state=state,
                top_k=payload.top_k,
                token_callback=token_callback,
                retrieval_callback=retrieval_callback,
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
        last_emit = time.monotonic()
        stream_start = time.monotonic()

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
        task = asyncio.create_task(run_agent())
        try:
            while not done.is_set() or not queue.empty():
                if await http_request.is_disconnected():
                    # Stop streaming immediately when the client disconnects.
                    disconnect_event.set()
                    cancel_event.set()
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
                        last_emit = now
                    continue
                if item.get("kind") == "event":
                    # Send debug events as fully-formed SSE payloads.
                    yield emit(item["payload"])
                    continue
                # Stream each delta as its own SSE message to avoid buffering output.
                delta = item.get("delta")
                if not isinstance(delta, str):
                    continue
                yield emit(
                    _wrap_payload(
                        "token.delta",
                        request_id,
                        payload.session_id,
                        {"delta": delta},
                    )
                )

            if disconnect_event.is_set():
                # Do not emit final/error events after a client disconnects.
                return

            await task

            if error:
                code, message = _map_error(error)
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

            try:
                # TX #2: persist assistant + checkpoint only after a successful run.
                await messages_repo.add_message(db, payload.session_id, "assistant", answer)
                await checkpoints_repo.add_checkpoint(db, payload.session_id, checkpoint_state)
                await db.commit()
            except Exception as exc:
                # Roll back to avoid partial writes if post-run persistence fails.
                await db.rollback()
                code, message = _map_error(exc)
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

            if not payload.audio:
                yield emit(_wrap_payload("done", request_id, payload.session_id, {}))
                return
            if await http_request.is_disconnected():
                # Skip TTS if the client disconnects after the text response.
                return
            try:
                tts = get_tts_provider()
                audio_bytes = await tts.synthesize(answer)
                audio_id, _path, audio_url = await save_audio(
                    session=db,
                    tenant_id=principal.tenant_id,
                    audio_bytes=audio_bytes,
                    base_url=settings.audio_base_url,
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
            record_stream_duration((time.monotonic() - stream_start) * 1000.0)

    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_stream(),
        headers=headers,
        media_type="text/event-stream",
        background=BackgroundTask(lease.release),
    )
