from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.agent.graph import run_graph
from nexusrag.core.errors import ProviderConfigError
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


def _sse_event(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: message\ndata: {data}\n\n"


@router.post("/run")
async def run(request: RunRequest, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    await sessions_repo.upsert_session(db, request.session_id, request.tenant_id)
    await messages_repo.add_message(db, request.session_id, "user", request.message)
    await db.commit()

    retriever = LocalPgVectorRetriever(db)
    llm = GeminiVertexProvider()

    queue: asyncio.Queue[str] = asyncio.Queue()
    done = asyncio.Event()
    final_state: AgentState | None = None
    error: Exception | None = None

    loop = asyncio.get_running_loop()

    def token_callback(delta: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, delta)

    async def run_agent() -> None:
        nonlocal final_state, error
        try:
            state: AgentState = {
                "session_id": request.session_id,
                "tenant_id": request.tenant_id,
                "corpus_id": request.corpus_id,
                "user_message": request.message,
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
                top_k=request.top_k,
                token_callback=token_callback,
            )
        except Exception as exc:
            error = exc
            logger.exception("run_graph failed")
        finally:
            done.set()

    async def event_stream() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(run_agent())
        try:
            while not done.is_set() or not queue.empty():
                try:
                    delta = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                yield _sse_event({"type": "token.delta", "data": {"delta": delta}})

            await task

            if error:
                if isinstance(error, ProviderConfigError):
                    payload = {
                        "type": "error",
                        "data": {
                            "message": str(error),
                            "code": "provider_config_error",
                        },
                    }
                else:
                    payload = {
                        "type": "error",
                        "data": {
                            "message": "Internal error during generation.",
                            "code": "internal_error",
                        },
                    }
                yield _sse_event(payload)
                return

            assert final_state is not None
            answer = final_state.get("answer") or ""
            citations = final_state.get("citations", [])
            checkpoint_state = final_state.get("checkpoint_state") or {}

            await messages_repo.add_message(db, request.session_id, "assistant", answer)
            await checkpoints_repo.add_checkpoint(db, request.session_id, checkpoint_state)
            await db.commit()

            yield _sse_event({
                "type": "message.final",
                "data": {"text": answer, "citations": citations},
            })
        finally:
            if not task.done():
                task.cancel()

    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), headers=headers, media_type="text/event-stream")
