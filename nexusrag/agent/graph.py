from __future__ import annotations

import asyncio
import time
from typing import Callable

from langgraph.graph import END, StateGraph

from nexusrag.agent.prompts import build_messages
from nexusrag.domain.state import AgentState
from nexusrag.persistence.repos.messages import list_messages
from nexusrag.services.costs.metering import estimate_tokens


def build_graph(
    *,
    retriever,
    llm,
    session,
    top_k: int,
    token_callback: Callable[[str], None],
    retrieval_callback: Callable[[str, int], None] | None = None,
    max_output_tokens: int | None = None,
    token_estimator_ratio: float | None = None,
):
    graph = StateGraph(AgentState)

    async def load_history(state: AgentState) -> dict:
        started = time.monotonic()
        messages = await list_messages(session, state["session_id"])
        history = [{"role": msg.role, "content": msg.content} for msg in messages]
        timings = dict(state.get("timings_ms") or {})
        timings["history_load"] = (time.monotonic() - started) * 1000.0
        return {"history": history, "timings_ms": timings}

    async def retrieve(state: AgentState) -> dict:
        started = time.monotonic()
        retrieved = await retriever.retrieve(
            state["tenant_id"],
            state["corpus_id"],
            state["user_message"],
            top_k,
        )
        if retrieval_callback is not None:
            # Surface provider and chunk counts for optional debug SSE events.
            provider_name = getattr(retriever, "last_provider", "unknown")
            retrieval_callback(provider_name, len(retrieved))
        citations = [
            {
                "source": item.get("source"),
                "score": item.get("score"),
                "metadata": item.get("metadata"),
            }
            for item in retrieved
        ]
        timings = dict(state.get("timings_ms") or {})
        timings["retrieval"] = (time.monotonic() - started) * 1000.0
        return {"retrieved": retrieved, "citations": citations, "timings_ms": timings}

    async def generate(state: AgentState) -> dict:
        started = time.monotonic()
        messages = build_messages(state["history"], state["retrieved"], state["user_message"])
        answer_parts: list[str] = []
        token_count = 0
        token_ratio = token_estimator_ratio or 4.0
        def run_stream() -> None:
            nonlocal token_count
            for delta in llm.stream(messages):
                if max_output_tokens is not None:
                    token_count += estimate_tokens(delta, ratio=token_ratio)
                    if token_count > max_output_tokens:
                        # Stop streaming once we hit the configured output budget.
                        break
                token_callback(delta)
                answer_parts.append(delta)

        await asyncio.to_thread(run_stream)
        timings = dict(state.get("timings_ms") or {})
        timings["generation"] = (time.monotonic() - started) * 1000.0
        return {"answer": "".join(answer_parts), "timings_ms": timings}

    async def save_checkpoint(state: AgentState) -> dict:
        started = time.monotonic()
        snapshot = {
            "session_id": state["session_id"],
            "tenant_id": state["tenant_id"],
            "corpus_id": state["corpus_id"],
            "history": state["history"],
            "retrieved": state["retrieved"],
            "answer": state.get("answer"),
            "citations": state.get("citations", []),
        }
        timings = dict(state.get("timings_ms") or {})
        timings["checkpoint_snapshot"] = (time.monotonic() - started) * 1000.0
        return {"checkpoint_state": snapshot, "timings_ms": timings}

    graph.add_node("load_history", load_history)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_node("save_checkpoint", save_checkpoint)

    graph.set_entry_point("load_history")
    graph.add_edge("load_history", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "save_checkpoint")
    graph.add_edge("save_checkpoint", END)

    return graph.compile()


async def run_graph(
    *,
    retriever,
    llm,
    session,
    state: AgentState,
    top_k: int,
    token_callback: Callable[[str], None],
    retrieval_callback: Callable[[str, int], None] | None = None,
    max_output_tokens: int | None = None,
    token_estimator_ratio: float | None = None,
) -> AgentState:
    graph = build_graph(
        retriever=retriever,
        llm=llm,
        session=session,
        top_k=top_k,
        token_callback=token_callback,
        retrieval_callback=retrieval_callback,
        max_output_tokens=max_output_tokens,
        token_estimator_ratio=token_estimator_ratio,
    )
    return await graph.ainvoke(state)
