from __future__ import annotations

import asyncio
from typing import Callable

from langgraph.graph import END, StateGraph

from nexusrag.agent.prompts import build_messages
from nexusrag.domain.state import AgentState
from nexusrag.persistence.repos.messages import list_messages


def build_graph(
    *,
    retriever,
    llm,
    session,
    top_k: int,
    token_callback: Callable[[str], None],
    retrieval_callback: Callable[[str, int], None] | None = None,
):
    graph = StateGraph(AgentState)

    async def load_history(state: AgentState) -> dict:
        messages = await list_messages(session, state["session_id"])
        history = [{"role": msg.role, "content": msg.content} for msg in messages]
        return {"history": history}

    async def retrieve(state: AgentState) -> dict:
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
        return {"retrieved": retrieved, "citations": citations}

    async def generate(state: AgentState) -> dict:
        messages = build_messages(state["history"], state["retrieved"], state["user_message"])
        answer_parts: list[str] = []
        def run_stream() -> None:
            for delta in llm.stream(messages):
                token_callback(delta)
                answer_parts.append(delta)

        await asyncio.to_thread(run_stream)
        return {"answer": "".join(answer_parts)}

    async def save_checkpoint(state: AgentState) -> dict:
        snapshot = {
            "session_id": state["session_id"],
            "tenant_id": state["tenant_id"],
            "corpus_id": state["corpus_id"],
            "history": state["history"],
            "retrieved": state["retrieved"],
            "answer": state.get("answer"),
            "citations": state.get("citations", []),
        }
        return {"checkpoint_state": snapshot}

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
) -> AgentState:
    graph = build_graph(
        retriever=retriever,
        llm=llm,
        session=session,
        top_k=top_k,
        token_callback=token_callback,
        retrieval_callback=retrieval_callback,
    )
    return await graph.ainvoke(state)
