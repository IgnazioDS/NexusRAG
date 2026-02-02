from __future__ import annotations

from typing import Protocol


class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> bytes:
        ...
