from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import get_db
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.core.config import get_settings
from nexusrag.domain.models import EncryptedBlob
from nexusrag.services.audio.storage import AUDIO_DIR
from nexusrag.services.crypto import CRYPTO_RESOURCE_AUDIO, decrypt_blob


router = APIRouter(tags=["audio"], responses=DEFAULT_ERROR_RESPONSES)


@router.get("/audio/{audio_id}.mp3", response_class=Response, response_model=None)
async def get_audio(audio_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    # Serve local audio files for dev; decrypt payloads when crypto is enabled.
    settings = get_settings()
    if settings.crypto_enabled:
        blob = (
            await db.execute(
                select(EncryptedBlob).where(
                    EncryptedBlob.resource_type == CRYPTO_RESOURCE_AUDIO,
                    EncryptedBlob.resource_id == audio_id,
                )
            )
        ).scalar_one_or_none()
        if blob is not None:
            payload = await decrypt_blob(db, blob=blob)
            return Response(content=payload, media_type="audio/mpeg")
    path = AUDIO_DIR / f"{audio_id}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type="audio/mpeg")
