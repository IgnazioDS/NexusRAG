from __future__ import annotations

from nexusrag.core.config import get_settings
from nexusrag.core.errors import TTSConfigMissingError
from nexusrag.providers.tts.fake_tts import FakeTTSProvider
from nexusrag.providers.tts.openai_tts import OpenAITTSProvider


def get_tts_provider():
    settings = get_settings()
    provider = (settings.tts_provider or "none").lower()

    if provider == "none":
        # Surface a stable error so callers can emit a non-fatal audio.error event.
        raise TTSConfigMissingError("TTS_PROVIDER is set to none")
    if provider == "fake":
        return FakeTTSProvider()
    if provider == "openai":
        return OpenAITTSProvider()

    raise TTSConfigMissingError(f"Unsupported TTS provider: {provider}")
