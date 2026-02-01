from __future__ import annotations

from typing import Any, Optional, TypedDict


class AgentState(TypedDict):
    session_id: str
    tenant_id: str
    corpus_id: str
    user_message: str
    history: list[dict[str, Any]]
    retrieved: list[dict[str, Any]]
    answer: Optional[str]
    citations: list[dict[str, Any]]
    checkpoint_state: Optional[dict[str, Any]]
