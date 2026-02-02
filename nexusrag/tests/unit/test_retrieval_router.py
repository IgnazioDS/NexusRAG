from __future__ import annotations

from dataclasses import dataclass

import pytest

from nexusrag.core.errors import RetrievalConfigError
from nexusrag.providers.retrieval.router import RetrievalRouter, parse_retrieval_config


@dataclass
class DummyCorpus:
    provider_config_json: dict


class StubProvider:
    def __init__(self) -> None:
        self.called = None

    async def retrieve(self, tenant_id: str, corpus_id: str, query: str, top_k: int) -> list[dict]:
        self.called = (tenant_id, corpus_id, query, top_k)
        return [{"text": "x", "score": 1.0, "source": "stub", "metadata": {}}]


@pytest.mark.asyncio
async def test_router_routes_local_provider() -> None:
    config = {"retrieval": {"provider": "local_pgvector", "top_k_default": 7}}
    stub = StubProvider()

    async def loader(_session, _corpus_id: str, _tenant_id: str):
        return DummyCorpus(provider_config_json=config)

    router = RetrievalRouter(
        session=None,  # type: ignore[arg-type]
        corpus_loader=loader,
        provider_factories={"local_pgvector": lambda _cfg: stub},
    )

    results = await router.retrieve("t1", "c1", "query", top_k=0)
    assert results[0]["source"] == "stub"
    assert stub.called == ("t1", "c1", "query", 7)


def test_parse_retrieval_config_invalid() -> None:
    with pytest.raises(RetrievalConfigError):
        parse_retrieval_config(None)
