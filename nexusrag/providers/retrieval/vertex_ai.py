from __future__ import annotations

import asyncio
import time
from typing import Any

from google.api_core.exceptions import GoogleAPICallError, RetryError

from nexusrag.core.errors import (
    VertexRetrievalAuthError,
    VertexRetrievalConfigError,
    VertexRetrievalError,
)
from nexusrag.services.audit import record_system_event
from nexusrag.services.resilience import CircuitBreaker, get_resilience_redis, retry_async
from nexusrag.services.telemetry import record_external_call


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
        self._breaker: CircuitBreaker | None = None

    async def _get_breaker(self) -> CircuitBreaker:
        # Share breaker state across instances for Vertex retrieval calls.
        if self._breaker is not None:
            return self._breaker
        redis = await get_resilience_redis()

        async def _on_transition(name: str, state: str) -> None:
            await record_system_event(
                event_type=f"system.circuit_breaker.{state}",
                metadata={"integration": name},
            )

        self._breaker = CircuitBreaker(
            "retrieval.gcp_vertex",
            redis=redis,
            on_transition=_on_transition,
        )
        return self._breaker

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        start = time.monotonic()
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
        breaker = await self._get_breaker()
        await breaker.before_call()
        start = time.monotonic()
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

            def _retryable(exc: Exception) -> bool:
                if isinstance(exc, (asyncio.TimeoutError, ConnectionError, TimeoutError)):
                    return True
                if isinstance(exc, (GoogleAPICallError, RetryError)):
                    code = getattr(exc, "code", None)
                    if callable(code):
                        code = code()
                    return int(code or 0) >= 500
                return False

            results = await retry_async(lambda: asyncio.to_thread(_search), retryable=_retryable)
            await breaker.record_success()
            record_external_call(
                integration="retrieval.gcp_vertex",
                latency_ms=(time.monotonic() - start) * 1000.0,
                success=True,
            )
        except Exception as exc:
            await breaker.record_failure()
            record_external_call(
                integration="retrieval.gcp_vertex",
                latency_ms=(time.monotonic() - start) * 1000.0,
                success=False,
            )
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
