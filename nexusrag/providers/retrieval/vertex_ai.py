from __future__ import annotations

import asyncio
from typing import Any

from nexusrag.core.errors import (
    VertexRetrievalAuthError,
    VertexRetrievalConfigError,
    VertexRetrievalError,
)


class VertexAIRetriever:
    def __init__(
        self,
        project: str,
        location: str,
        resource_id: str,
        client: Any | None = None,
    ) -> None:
        # Validate early so callers get stable config errors instead of SDK stack traces.
        if not project or not location or not resource_id:
            raise VertexRetrievalConfigError("project, location, and resource_id are required")
        self._project = project
        self._location = location
        # Keep the name generic so we can map to different Vertex retrieval resources later.
        self._resource_id = resource_id
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google.cloud.discoveryengine_v1 import SearchServiceClient
        except Exception as exc:  # pragma: no cover - environment-specific import
            raise VertexRetrievalError(
                "Vertex Discovery Engine client not available. Install google-cloud-discoveryengine."
            ) from exc

        self._client = SearchServiceClient()
        return self._client

    async def retrieve(self, tenant_id: str, corpus_id: str, query: str, top_k: int) -> list[dict]:
        # tenant_id/corpus_id are unused for Vertex retrieval but kept for a unified interface.
        client = self._get_client()
        serving_config = (
            f"projects/{self._project}/locations/{self._location}/dataStores/"
            f"{self._resource_id}/servingConfigs/default_search"
        )
        request = {
            "serving_config": serving_config,
            "query": query,
            "page_size": top_k,
        }

        try:
            def _search() -> list[Any]:
                return list(client.search(request=request))

            results = await asyncio.to_thread(_search)
        except Exception as exc:
            error_name = exc.__class__.__name__
            if error_name in {"DefaultCredentialsError", "RefreshError", "PermissionDenied", "Unauthenticated"}:
                raise VertexRetrievalAuthError(
                    "Vertex retrieval auth error. Provide ADC credentials."
                ) from exc
            raise VertexRetrievalError("Vertex retrieval failed.") from exc

        items: list[dict] = []
        for result in results:
            doc = getattr(result, "document", None)
            if doc is None and isinstance(result, dict):
                doc = result.get("document")

            data: dict[str, Any] = {}
            if doc is not None:
                if hasattr(doc, "struct_data"):
                    data = dict(doc.struct_data)
                elif isinstance(doc, dict):
                    data = doc.get("struct_data") or doc

            text = data.get("text") or data.get("snippet") or ""
            source = data.get("uri") or data.get("link") or data.get("id") or "vertex_ai"

            score = getattr(result, "relevance_score", None)
            if score is None and isinstance(result, dict):
                score = result.get("relevance_score") or result.get("score")
            try:
                score = float(score) if score is not None else 0.0
            except (TypeError, ValueError):
                score = 0.0
            score = max(0.0, min(1.0, score))

            items.append(
                {
                    "text": text,
                    "score": score,
                    "source": source,
                    "metadata": data,
                }
            )
        return items
