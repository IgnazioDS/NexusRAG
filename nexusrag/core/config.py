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

    # Redis connection for ingestion queue and worker coordination.
    redis_url: str = "redis://localhost:6379/0"
    # Keep queue name configurable for multi-environment isolation.
    ingest_queue_name: str = "ingest"
    # Limit retries for transient ingestion failures to avoid infinite loops.
    ingest_max_retries: int = 3
    # Inline mode executes ingestion immediately for deterministic tests.
    ingest_execution_mode: str = "queue"
    # Emit worker heartbeats for ops health and alerting.
    worker_heartbeat_interval_s: int = 10
    # Treat stale heartbeats as degraded to surface worker outages.
    worker_heartbeat_stale_after_s: int = 60
    # Require API key auth for all protected endpoints by default.
    auth_enabled: bool = True
    # Allow legacy X-Tenant-Id + X-Role only when explicitly enabled for dev.
    auth_dev_bypass: bool = False
    # Header used to carry the bearer API key.
    auth_api_key_header: str = "Authorization"
    # Small cache window to reduce auth DB lookups without delaying revocations too long.
    auth_cache_ttl_s: int = 15

    google_cloud_project: str | None = None
    google_cloud_location: str | None = None
    gemini_model: str = "gemini-2.0-flash-001"
    # Streaming timeout avoids hanging connections if the provider stalls.
    vertex_stream_timeout_s: int = 90
    # Toggle verbose SSE debug events without changing the API surface.
    debug_events: bool = False
    # Select the LLM provider for dev/test (vertex or fake).
    llm_provider: str = "vertex"

    # TTS provider selection: none/openai/fake for local development.
    tts_provider: str = "none"
    openai_api_key: str | None = None
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    # Base URL used to build audio URLs in SSE payloads.
    audio_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
