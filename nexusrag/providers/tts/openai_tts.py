from __future__ import annotations

from typing import Any

import httpx

from nexusrag.core.config import get_settings
from nexusrag.core.errors import TTSAuthError, TTSConfigMissingError, TTSError


class OpenAITTSProvider:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._client = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        # Reuse a single client per provider for connection pooling.
        self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def synthesize(self, text: str) -> bytes:
        api_key = self._settings.openai_api_key
        if not api_key:
            raise TTSConfigMissingError("OPENAI_API_KEY is required for OpenAI TTS")

        payload = {
            "model": self._settings.openai_tts_model,
            "voice": self._settings.openai_tts_voice,
            "input": text,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        client = self._get_client()

        try:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                json=payload,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise TTSError("OpenAI TTS request failed.") from exc

        if response.status_code in {401, 403}:
            raise TTSAuthError("OpenAI TTS auth error: check OPENAI_API_KEY.")
        if response.status_code >= 400:
            raise TTSError(f"OpenAI TTS error: {response.status_code}")

        return response.content
