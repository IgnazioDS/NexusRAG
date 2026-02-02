from __future__ import annotations

from typing import Protocol


class RetrievalProvider(Protocol):
    async def retrieve(self, tenant_id: str, corpus_id: str, query: str, top_k: int) -> list[dict]:
        ...
