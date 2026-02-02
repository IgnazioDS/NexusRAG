from __future__ import annotations

from pathlib import Path
from uuid import uuid4


AUDIO_DIR = Path("var") / "audio"


def save_audio(audio_bytes: bytes, base_url: str) -> tuple[str, Path, str]:
    # Store files locally for dev; production will use object storage.
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_id = str(uuid4())
    filename = f"{audio_id}.mp3"
    path = AUDIO_DIR / filename
    path.write_bytes(audio_bytes)
    audio_url = f"{base_url.rstrip('/')}/audio/{filename}"
    return audio_id, path, audio_url
