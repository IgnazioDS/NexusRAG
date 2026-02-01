from __future__ import annotations

import pytest

from nexusrag.core.errors import RetrievalError
from nexusrag.providers.retrieval import local_pgvector


class DummySession:
    # Guard against unexpected DB access when we validate embedding invariants.
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("execute should not be called for invalid embeddings")


@pytest.mark.asyncio
async def test_retriever_rejects_dimension_mismatch(monkeypatch) -> None:
    # Force an invalid embedding length to exercise the dimension guard.
    monkeypatch.setattr(local_pgvector, "embed_text", lambda _text: [0.0])

    retriever = local_pgvector.LocalPgVectorRetriever(DummySession())
    with pytest.raises(RetrievalError):
        await retriever.retrieve("c1", "query", top_k=5)
