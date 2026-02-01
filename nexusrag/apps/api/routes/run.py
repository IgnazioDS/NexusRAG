from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from nexusrag.agent.graph import run_graph
from nexusrag.core.errors import ProviderConfigError, RetrievalError
from nexusrag.domain.state import AgentState
from nexusrag.persistence.repos import checkpoints as checkpoints_repo
from nexusrag.persistence.repos import messages as messages_repo
from nexusrag.persistence.repos import sessions as sessions_repo
from nexusrag.providers.llm.gemini_vertex import GeminiVertexProvider
from nexusrag.providers.retrieval.local_pgvector import LocalPgVectorRetriever
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
    if isinstance(exc, RetrievalError):
        return "RETRIEVAL_ERROR", "Retrieval failed."
    if isinstance(exc, SQLAlchemyError):
        return "DB_ERROR", "Database error during run."
    return "UNKNOWN_ERROR", "Internal error during generation."


@router.post("/run")
async def run(
    payload: RunRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    # Per-request identifier for tracing a single streamed conversation.
    request_id = str(uuid4())
    # Persist the user message before generation so history is consistent even if the model fails.
    await sessions_repo.upsert_session(db, payload.session_id, payload.tenant_id)
    await messages_repo.add_message(db, payload.session_id, "user", payload.message)
    await db.commit()

    retriever = LocalPgVectorRetriever(db)
    llm = GeminiVertexProvider()

    queue: asyncio.Queue[str] = asyncio.Queue()
    done = asyncio.Event()
    final_state: AgentState | None = None
    error: Exception | None = None
    disconnect_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def token_callback(delta: str) -> None:
        # Drop tokens once the client disconnects to avoid buffering unused output.
        if disconnect_event.is_set():
            return
        loop.call_soon_threadsafe(queue.put_nowait, delta)

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
                    break
                try:
                    delta = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                # Stream each delta as its own SSE message to avoid buffering output.
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
                await messages_repo.add_message(db, payload.session_id, "assistant", answer)
                await checkpoints_repo.add_checkpoint(db, payload.session_id, checkpoint_state)
                await db.commit()
            except Exception as exc:
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
        finally:
            if not task.done():
                task.cancel()

    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), headers=headers, media_type="text/event-stream")
