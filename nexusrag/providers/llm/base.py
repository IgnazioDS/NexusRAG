from __future__ import annotations

from typing import Iterable, Protocol


class LLMProvider(Protocol):
    def stream(self, messages: list[dict]) -> Iterable[str]:
        ...
