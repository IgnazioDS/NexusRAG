from __future__ import annotations

from typing import Iterable


class FakeLLMProvider:
    def __init__(self, response: str = "This is a fake response.") -> None:
        # Deterministic response keeps tests stable without external calls.
        self._response = response

    def stream(self, messages: list[dict]) -> Iterable[str]:
        # Ignore messages to avoid variability; yield word tokens for streaming tests.
        _ = messages
        for token in self._response.split():
            yield f"{token} "
