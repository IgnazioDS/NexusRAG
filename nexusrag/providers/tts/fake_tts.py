from __future__ import annotations


class FakeTTSProvider:
    def __init__(self) -> None:
        # Deterministic bytes allow tests to assert on output without external services.
        self._payload = b"FAKE_MP3_BYTES"

    async def synthesize(self, text: str) -> bytes:
        # Ignore input to keep output deterministic and cheap for tests.
        _ = text
        return self._payload
