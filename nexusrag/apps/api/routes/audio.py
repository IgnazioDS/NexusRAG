from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from fastapi.responses import FileResponse

from nexusrag.services.audio.storage import AUDIO_DIR


router = APIRouter(tags=["audio"], responses=DEFAULT_ERROR_RESPONSES)


@router.get("/audio/{audio_id}.mp3")
async def get_audio(audio_id: str) -> FileResponse:
    # Serve local audio files for dev; production will use object storage.
    path = AUDIO_DIR / f"{audio_id}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type="audio/mpeg")
