from __future__ import annotations

import time
from typing import Any

from nexusrag_sdk import ApiClient, Configuration
from nexusrag_sdk.api.default_api import DefaultApi
from nexusrag_sdk.exceptions import ApiException


class RetryingApiClient(ApiClient):
    """ApiClient that retries 429/503 responses with backoff."""

    def __init__(self, configuration: Configuration, max_retries: int = 2) -> None:
        super().__init__(configuration)
        self._max_retries = max_retries

    def call_api(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        attempt = 0
        while True:
            try:
                return super().call_api(*args, **kwargs)
            except ApiException as exc:
                if exc.status not in {429, 503} or attempt >= self._max_retries:
                    raise
                retry_after = _retry_after_seconds(getattr(exc, "headers", None))
                if retry_after is None:
                    retry_after = min(2.0, 0.25 * (2 ** attempt))
                time.sleep(retry_after)
                attempt += 1


def _retry_after_seconds(headers: dict[str, str] | None) -> float | None:
    if not headers:
        return None
    retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            return None
    retry_ms = headers.get("X-RateLimit-Retry-After-Ms")
    if retry_ms:
        try:
            return float(retry_ms) / 1000.0
        except ValueError:
            return None
    return None


def create_client(api_key: str, base_url: str = "http://localhost:8000", max_retries: int = 2) -> DefaultApi:
    config = Configuration(host=base_url)
    config.access_token = api_key
    api_client = RetryingApiClient(config, max_retries=max_retries)
    return DefaultApi(api_client)
