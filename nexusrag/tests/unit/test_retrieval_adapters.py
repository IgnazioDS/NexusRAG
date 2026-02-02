from __future__ import annotations

import pytest

from nexusrag.providers.retrieval.bedrock_kb import BedrockKnowledgeBaseRetriever
from nexusrag.providers.retrieval.vertex_ai import VertexAIRetriever


class DummyBedrockClient:
    def retrieve(self, **_kwargs):
        return {
            "retrievalResults": [
                {
                    "content": {"text": "hello bedrock"},
                    "location": {"s3Location": {"uri": "s3://demo/doc"}},
                    "score": 0.42,
                    "metadata": {"title": "Demo"},
                }
            ]
        }


@pytest.mark.asyncio
async def test_bedrock_adapter_normalization() -> None:
    retriever = BedrockKnowledgeBaseRetriever(
        knowledge_base_id="kb1",
        region="us-east-1",
        client=DummyBedrockClient(),
    )
    results = await retriever.retrieve("t1", "c1", "query", top_k=3)
    assert results[0]["text"] == "hello bedrock"
    assert results[0]["source"].startswith("s3://")
    assert 0.0 <= results[0]["score"] <= 1.0


class DummyVertexClient:
    def search(self, request):
        assert request["page_size"] == 3
        return [
            {
                "document": {
                    "struct_data": {"text": "hello vertex", "uri": "gs://demo/doc"}
                },
                "relevance_score": 0.9,
            }
        ]


@pytest.mark.asyncio
async def test_vertex_adapter_normalization() -> None:
    retriever = VertexAIRetriever(
        project="proj",
        location="us-central1",
        datastore_id="ds1",
        client=DummyVertexClient(),
    )
    results = await retriever.retrieve("t1", "c1", "query", top_k=3)
    assert results[0]["text"] == "hello vertex"
    assert results[0]["source"].startswith("gs://")
    assert 0.0 <= results[0]["score"] <= 1.0
