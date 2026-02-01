from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


# Keep embedding dimension centralized to prevent drift across DB and retrieval logic.
EMBED_DIM = 768


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "nexusrag"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://nexusrag:nexusrag@localhost:5432/nexusrag"

    google_cloud_project: str | None = None
    google_cloud_location: str | None = None
    gemini_model: str = "gemini-2.0-flash-001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
