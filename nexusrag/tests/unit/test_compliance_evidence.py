from __future__ import annotations

from nexusrag.core.config import get_settings
from nexusrag.services.compliance.evidence import sanitize_config_snapshot


def test_sanitize_config_snapshot_redacts_sensitive_keys(monkeypatch) -> None:
    # Keep evidence config exports safe by redacting known secret-bearing settings.
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("BACKUP_SIGNING_KEY", "another-secret")
    get_settings.cache_clear()

    sanitized = sanitize_config_snapshot()

    assert sanitized["openai_api_key"] == "[REDACTED]"
    assert sanitized["backup_signing_key"] == "[REDACTED]"
    get_settings.cache_clear()
