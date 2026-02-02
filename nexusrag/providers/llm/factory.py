from __future__ import annotations

import threading

from nexusrag.core.config import get_settings
from nexusrag.providers.llm.fake import FakeLLMProvider
from nexusrag.providers.llm.gemini_vertex import GeminiVertexProvider


def get_llm_provider(request_id: str, cancel_event: threading.Event):
    settings = get_settings()
    provider = (settings.llm_provider or "vertex").lower()

    if provider == "fake":
        return FakeLLMProvider()
    return GeminiVertexProvider(request_id=request_id, cancel_event=cancel_event)
