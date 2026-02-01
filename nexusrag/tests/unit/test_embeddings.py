from __future__ import annotations

from nexusrag.core.config import EMBED_DIM
from nexusrag.ingestion.embeddings import embed_text


def test_embed_text_is_deterministic() -> None:
    vec1 = embed_text("NexusRAG deterministic embedding")
    vec2 = embed_text("NexusRAG deterministic embedding")

    assert vec1 == vec2
    assert len(vec1) == EMBED_DIM


def test_embed_text_changes_with_input() -> None:
    vec1 = embed_text("alpha")
    vec2 = embed_text("beta")

    assert vec1 != vec2
