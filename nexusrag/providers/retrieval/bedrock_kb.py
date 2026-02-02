from __future__ import annotations

import asyncio
from typing import Any

from nexusrag.core.errors import AwsAuthError, AwsConfigMissingError, AwsRetrievalError


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
        request = {
            "knowledgeBaseId": self._knowledge_base_id,
            "retrievalQuery": {"text": query},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {"numberOfResults": top_k}
            },
        }
        try:
            response = await asyncio.to_thread(client.retrieve, **request)
        except Exception as exc:
            error_name = exc.__class__.__name__
            if error_name in {"NoCredentialsError", "PartialCredentialsError"}:
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
