from __future__ import annotations

from typing import Any


def build_messages(history: list[dict[str, Any]], retrieved: list[dict[str, Any]], user_message: str) -> list[dict[str, str]]:
    context_lines = []
    for idx, chunk in enumerate(retrieved, start=1):
        source = chunk.get("source", "unknown")
        text = chunk.get("text", "")
        context_lines.append(f"[{idx}] ({source}) {text}")

    system_prompt = (
        "You are NexusRAG, a helpful assistant. Answer the user using the provided context. "
        "If the answer is not in the context, say you don't know."
    )

    if context_lines:
        system_prompt += "\n\nContext:\n" + "\n".join(context_lines)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend({"role": msg["role"], "content": msg["content"]} for msg in history)
    messages.append({"role": "user", "content": user_message})
    return messages
