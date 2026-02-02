from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.errors import RetrievalConfigError
from nexusrag.persistence.repos.corpora import get_corpus_for_tenant
from nexusrag.providers.retrieval.bedrock_kb import BedrockKnowledgeBaseRetriever
from nexusrag.providers.retrieval.config import parse_retrieval_config
from nexusrag.providers.retrieval.local_pgvector import LocalPgVectorRetriever
from nexusrag.providers.retrieval.vertex_ai import VertexAIRetriever


class RetrievalRouter:
    def __init__(
        self,
        session: AsyncSession,
        corpus_loader: Callable[[AsyncSession, str, str], Any] | None = None,
        provider_factories: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
    ) -> None:
        self._session = session
        # Expose the last provider for optional debug events without changing return types.
        self.last_provider: str | None = None
        # Allow injecting loaders/providers for tests without hitting external systems.
        self._corpus_loader = corpus_loader or get_corpus_for_tenant
        self._provider_factories = provider_factories or {
            "local_pgvector": lambda _cfg: LocalPgVectorRetriever(self._session),
            "aws_bedrock_kb": lambda cfg: BedrockKnowledgeBaseRetriever(
                knowledge_base_id=cfg["knowledge_base_id"],
                region=cfg["region"],
            ),
            "gcp_vertex": lambda cfg: VertexAIRetriever(
                project=cfg["project"],
                location=cfg["location"],
                resource_id=cfg["resource_id"],
            ),
        }

    async def retrieve(self, tenant_id: str, corpus_id: str, query: str, top_k: int) -> list[dict]:
        corpus = await self._corpus_loader(self._session, corpus_id, tenant_id)
        if corpus is None:
            raise RetrievalConfigError("corpus not found")

        retrieval = parse_retrieval_config(corpus.provider_config_json)
        provider_name = retrieval["provider"]
        provider_factory = self._provider_factories.get(provider_name)
        if provider_factory is None:
            raise RetrievalConfigError("retrieval provider not registered")

        effective_top_k = top_k or retrieval.get("top_k_default") or 5
        # Clamp to a safe range to avoid unbounded provider calls.
        effective_top_k = max(1, min(int(effective_top_k), 20))

        # Track provider selection for optional debug output downstream.
        self.last_provider = provider_name
        provider = provider_factory(retrieval)
        return await provider.retrieve(tenant_id, corpus_id, query, effective_top_k)
