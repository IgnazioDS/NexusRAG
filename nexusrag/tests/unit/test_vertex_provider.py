from __future__ import annotations

import pytest

from nexusrag.core.config import get_settings
from nexusrag.core.errors import ProviderConfigError
from nexusrag.providers.llm.gemini_vertex import GeminiVertexProvider


def test_vertex_provider_missing_config(monkeypatch) -> None:
    # Force missing config and clear cached settings for deterministic behavior.
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    get_settings.cache_clear()

    provider = GeminiVertexProvider()
    with pytest.raises(ProviderConfigError):
        next(iter(provider.stream([])))
