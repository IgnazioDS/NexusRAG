from __future__ import annotations

import pytest

from nexusrag.providers.tts.fake_tts import FakeTTSProvider


@pytest.mark.asyncio
async def test_fake_tts_is_deterministic() -> None:
    provider = FakeTTSProvider()
    data1 = await provider.synthesize("hello")
    data2 = await provider.synthesize("world")
    assert data1 == data2
    assert data1
