from __future__ import annotations

import math

import pytest

from nexusrag.core.config import EMBED_DIM, get_settings
from nexusrag.core.errors import ProviderConfigError
from nexusrag.ingestion import embeddings
from nexusrag.ingestion.embeddings import embed_text


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    # Settings is lru_cached; clear before and after so env changes via
    # monkeypatch take effect and never leak between tests.
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_embed_text_is_deterministic() -> None:
    vec1 = embed_text("NexusRAG deterministic embedding")
    vec2 = embed_text("NexusRAG deterministic embedding")

    assert vec1 == vec2
    assert len(vec1) == EMBED_DIM


def test_embed_text_changes_with_input() -> None:
    vec1 = embed_text("alpha")
    vec2 = embed_text("beta")

    assert vec1 != vec2


def test_fake_is_default_and_normalized() -> None:
    # Default provider is "fake": no creds required, unit-norm vector.
    vec = embed_text("a short sentence with several tokens")
    assert len(vec) == EMBED_DIM
    norm = math.sqrt(sum(v * v for v in vec))
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_vertex_provider_missing_creds_raises(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "vertex")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ProviderConfigError):
        embed_text("needs vertex creds")


def test_vertex_provider_uses_real_embeddings_no_fallback(monkeypatch) -> None:
    # When provider is "vertex", embed_text MUST use the Vertex model and
    # never silently fall back to the fake (lexical) embedding.
    monkeypatch.setenv("EMBEDDING_PROVIDER", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    get_settings.cache_clear()

    sentinel = [0.123] * EMBED_DIM

    class _StubEmbedding:
        values = sentinel

    class _StubModel:
        def get_embeddings(self, texts):
            assert texts == ["semantic please"]
            return [_StubEmbedding()]

    monkeypatch.setattr(embeddings, "_get_vertex_model", lambda: _StubModel())

    vec = embed_text("semantic please")
    assert vec == sentinel
    # And it is NOT the fake hashed-bag-of-words vector for the same text.
    assert vec != embeddings._embed_text_fake("semantic please")


def test_vertex_provider_dim_mismatch_raises(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    get_settings.cache_clear()

    class _StubEmbedding:
        values = [0.1, 0.2, 0.3]  # wrong dimension

    class _StubModel:
        def get_embeddings(self, texts):
            return [_StubEmbedding()]

    monkeypatch.setattr(embeddings, "_get_vertex_model", lambda: _StubModel())

    with pytest.raises(ValueError):
        embed_text("wrong dim")
