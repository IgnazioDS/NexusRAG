from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.services.crypto import CRYPTO_RESOURCE_AUDIO, store_encrypted_blob


AUDIO_DIR = Path("var") / "audio"


async def save_audio(
    *,
    session: AsyncSession,
    tenant_id: str,
    audio_bytes: bytes,
    base_url: str,
) -> tuple[str, Path, str]:
    # Store files locally for dev; encrypt payloads when crypto is enabled.
    settings = get_settings()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_id = str(uuid4())
    filename = f"{audio_id}.mp3"
    path = AUDIO_DIR / filename
    if settings.crypto_enabled:
        blob = await store_encrypted_blob(
            session,
            tenant_id=tenant_id,
            resource_type=CRYPTO_RESOURCE_AUDIO,
            resource_id=audio_id,
            plaintext=audio_bytes,
        )
        if blob is None:
            path.write_bytes(audio_bytes)
    else:
        path.write_bytes(audio_bytes)
    audio_url = f"{base_url.rstrip('/')}/audio/{filename}"
    return audio_id, path, audio_url
