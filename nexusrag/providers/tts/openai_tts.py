from __future__ import annotations

from typing import Any
import time

import httpx

from nexusrag.core.config import get_settings
from nexusrag.core.errors import TTSAuthError, TTSConfigMissingError, TTSError
from nexusrag.services.audit import record_system_event
from nexusrag.services.resilience import CircuitBreaker, get_resilience_redis, retry_async
from nexusrag.services.telemetry import record_external_call


class OpenAITTSProvider:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._settings = get_settings()
        self._client = client
        self._breaker: CircuitBreaker | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        # Reuse a single client per provider for connection pooling.
        timeout_s = self._settings.ext_call_timeout_ms / 1000.0
        self._client = httpx.AsyncClient(timeout=timeout_s)
        return self._client

    async def _get_breaker(self) -> CircuitBreaker:
        # Share breaker state across instances for TTS calls.
        if self._breaker is not None:
            return self._breaker
        redis = await get_resilience_redis()

        async def _on_transition(name: str, state: str) -> None:
            await record_system_event(
                event_type=f"system.circuit_breaker.{state}",
                metadata={"integration": name},
            )

        self._breaker = CircuitBreaker(
            "tts.openai",
            redis=redis,
            on_transition=_on_transition,
        )
        return self._breaker

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

        breaker = await self._get_breaker()
        start = time.monotonic()
        try:
            await breaker.before_call()

            async def _call() -> httpx.Response:
                return await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    json=payload,
                    headers=headers,
                )

            def _retryable(exc: Exception) -> bool:
                if isinstance(exc, httpx.TimeoutException):
                    return True
                if isinstance(exc, httpx.NetworkError):
                    return True
                status = getattr(exc, "status_code", None)
                return isinstance(status, int) and status >= 500

            response = await retry_async(_call, retryable=_retryable)
        except httpx.HTTPError as exc:
            await breaker.record_failure()
            record_external_call(
                integration="tts.openai",
                latency_ms=(time.monotonic() - start) * 1000.0,
                success=False,
            )
            raise TTSError("OpenAI TTS request failed.") from exc

        if response.status_code in {401, 403}:
            raise TTSAuthError("OpenAI TTS auth error: check OPENAI_API_KEY.")
        if response.status_code >= 500:
            await breaker.record_failure()
        if response.status_code >= 400:
            error = TTSError(f"OpenAI TTS error: {response.status_code}")
            setattr(error, "status_code", response.status_code)
            record_external_call(
                integration="tts.openai",
                latency_ms=(time.monotonic() - start) * 1000.0,
                success=False,
            )
            raise error

        await breaker.record_success()
        record_external_call(
            integration="tts.openai",
            latency_ms=(time.monotonic() - start) * 1000.0,
            success=True,
        )
        return response.content
