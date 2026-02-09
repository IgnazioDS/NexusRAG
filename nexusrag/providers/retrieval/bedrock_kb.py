from __future__ import annotations

import asyncio
import time
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from nexusrag.core.errors import AwsAuthError, AwsConfigMissingError, AwsRetrievalError
from nexusrag.services.audit import record_system_event
from nexusrag.services.resilience import CircuitBreaker, get_resilience_redis, retry_async
from nexusrag.services.telemetry import record_external_call


class BedrockKnowledgeBaseRetriever:
    def __init__(
        self,
        knowledge_base_id: str,
        region: str,
        client: Any | None = None,
    ) -> None:
        if not knowledge_base_id or not region:
            raise AwsConfigMissingError("knowledge_base_id and region are required")
        self._knowledge_base_id = knowledge_base_id
        self._region = region
        self._client = client
        self._breaker: CircuitBreaker | None = None

    async def _get_breaker(self) -> CircuitBreaker:
        # Share breaker state across instances for Bedrock retrieval calls.
        if self._breaker is not None:
            return self._breaker
        redis = await get_resilience_redis()

        async def _on_transition(name: str, state: str) -> None:
            await record_system_event(
                event_type=f"system.circuit_breaker.{state}",
                metadata={"integration": name},
            )

        self._breaker = CircuitBreaker(
            "retrieval.aws_bedrock",
            redis=redis,
            on_transition=_on_transition,
        )
        return self._breaker

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
        except Exception as exc:  # pragma: no cover - environment-specific import
            raise AwsRetrievalError("AWS SDK not available. Install boto3.") from exc

        self._client = boto3.client("bedrock-agent-runtime", region_name=self._region)
        return self._client

    async def retrieve(self, tenant_id: str, corpus_id: str, query: str, top_k: int) -> list[dict]:
        # tenant_id/corpus_id are unused for Bedrock KB but kept for a unified interface.
        client = self._get_client()
        breaker = await self._get_breaker()
        await breaker.before_call()
        request = {
            "knowledgeBaseId": self._knowledge_base_id,
            "retrievalQuery": {"text": query},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {"numberOfResults": top_k}
            },
        }
        start = time.monotonic()
        try:
            async def _call() -> dict:
                return await asyncio.to_thread(client.retrieve, **request)

            def _retryable(exc: Exception) -> bool:
                if isinstance(exc, (asyncio.TimeoutError, ConnectionError, TimeoutError)):
                    return True
                if isinstance(exc, (BotoCoreError, ClientError)):
                    status = getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
                    return isinstance(status, int) and status >= 500
                return False

            response = await retry_async(_call, retryable=_retryable)
            await breaker.record_success()
            record_external_call(
                integration="retrieval.aws_bedrock",
                latency_ms=(time.monotonic() - start) * 1000.0,
                success=True,
            )
        except Exception as exc:
            await breaker.record_failure()
            record_external_call(
                integration="retrieval.aws_bedrock",
                latency_ms=(time.monotonic() - start) * 1000.0,
                success=False,
            )
            error_name = exc.__class__.__name__
            if error_name in {"NoCredentialsError", "PartialCredentialsError"}:
                raise AwsAuthError("AWS credentials missing for Bedrock KB retrieval.") from exc
            if isinstance(exc, ClientError):
                status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                if status in {401, 403}:
                    raise AwsAuthError("AWS credentials missing for Bedrock KB retrieval.") from exc
            raise AwsRetrievalError("AWS Bedrock KB retrieval failed.") from exc

        results = response.get("retrievalResults", []) if isinstance(response, dict) else []
        items: list[dict] = []
        for result in results:
            content = result.get("content") if isinstance(result, dict) else None
            if isinstance(content, dict):
                text = content.get("text", "")
            else:
                text = content or ""

            location = result.get("location", {}) if isinstance(result, dict) else {}
            source = (
                location.get("s3Location", {}).get("uri")
                or location.get("type")
                or result.get("documentId")
                or "bedrock_kb"
            )

            score = result.get("score") or result.get("relevanceScore") or 0.0
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            score = max(0.0, min(1.0, score))

            items.append(
                {
                    "text": text,
                    "score": score,
                    "source": source,
                    "metadata": result.get("metadata", {}) if isinstance(result, dict) else {},
                }
            )
        return items
