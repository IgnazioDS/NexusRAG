from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
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
    ProviderConfigError,
    RetrievalConfigError,
    RetrievalError,
    SessionTenantMismatchError,
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
from nexusrag.apps.api.deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


class RunRequest(BaseModel):
    session_id: str
    tenant_id: str
    corpus_id: str
    message: str
    top_k: int = Field(default=5, ge=1, le=50)
    audio: bool = False


def _wrap_payload(payload_type: str, request_id: str, session_id: str, data: dict) -> dict:
    # Always include request/session identifiers for traceability across streamed events.
    return {
        "type": payload_type,
        "request_id": request_id,
        "session_id": session_id,
        "data": data,
    }


def _sse_message(payload: dict) -> str:
    # SSE framing invariants: event name must be "message" and data must be a compact JSON line.
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: message\ndata: {data}\n\n"


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
    if isinstance(exc, TTSError):
        return "TTS_ERROR", str(exc)
    return "TTS_ERROR", "TTS request failed."


@router.post("/run")
async def run(
    payload: RunRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # Per-request identifier for tracing a single streamed conversation.
    request_id = str(uuid4())
    # TX #1: persist session + user message so history is durable before streaming.
    try:
        await sessions_repo.upsert_session(db, payload.session_id, payload.tenant_id)
        await messages_repo.add_message(db, payload.session_id, "user", payload.message)
        await db.commit()
    except Exception as exc:
        # Ensure failed transactions do not poison the session state.
        await db.rollback()
        code, message = _map_error(exc)

        async def early_error_stream() -> AsyncGenerator[str, None]:
            # Emit a single SSE error event if pre-run persistence fails.
            yield _sse_message(
                _wrap_payload(
                    "error",
                    request_id,
                    payload.session_id,
                    {"code": code, "message": message},
                )
            )

        headers = {
            "Cache-Control": "no-cache",
            "Content-Type": "text/event-stream",
            "Connection": "keep-alive",
        }
        return StreamingResponse(early_error_stream(), headers=headers, media_type="text/event-stream")

    # Use a shared queue for token and debug events to preserve stream order.
    queue: asyncio.Queue[dict] = asyncio.Queue()
    done = asyncio.Event()
    final_state: AgentState | None = None
    error: Exception | None = None
    disconnect_event = asyncio.Event()
    # Thread-safe cancel signal so the blocking Vertex stream can exit promptly.
    cancel_event = threading.Event()
    # Use the same request-scoped session for read-only retrieval to avoid extra connections.
    retriever = RetrievalRouter(db)
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
                "tenant_id": payload.tenant_id,
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
                    continue
                if item.get("kind") == "event":
                    # Send debug events as fully-formed SSE payloads.
                    yield _sse_message(item["payload"])
                    continue
                # Stream each delta as its own SSE message to avoid buffering output.
                delta = item.get("delta")
                if not isinstance(delta, str):
                    continue
                yield _sse_message(
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
                yield _sse_message(
                    _wrap_payload(
                        "error",
                        request_id,
                        payload.session_id,
                        {"code": code, "message": message},
                    )
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

            yield _sse_message(
                _wrap_payload(
                    "message.final",
                    request_id,
                    payload.session_id,
                    {"text": answer, "citations": citations},
                )
            )

            if not payload.audio:
                return
            if await http_request.is_disconnected():
                # Skip TTS if the client disconnects after the text response.
                return
            try:
                tts = get_tts_provider()
                audio_bytes = await tts.synthesize(answer)
                audio_id, _path, audio_url = save_audio(audio_bytes, settings.audio_base_url)
                yield _sse_message(
                    _wrap_payload(
                        "audio.ready",
                        request_id,
                        payload.session_id,
                        {"audio_url": audio_url, "audio_id": audio_id, "mime": "audio/mpeg"},
                    )
                )
            except Exception as exc:
                code, message = _map_tts_error(exc)
                yield _sse_message(
                    _wrap_payload(
                        "audio.error",
                        request_id,
                        payload.session_id,
                        {"code": code, "message": message},
                    )
                )
        finally:
            if not task.done():
                task.cancel()

    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), headers=headers, media_type="text/event-stream")
