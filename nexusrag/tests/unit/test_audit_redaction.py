from __future__ import annotations

from nexusrag.services.audit import sanitize_metadata


def test_audit_redacts_tokens_and_secrets() -> None:
    # Redact token and secret fields in audit metadata.
    payload = {
        "id_token": "secret-token",
        "access_token": "secret-access",
        "client_secret": "super-secret",
        "nested": {"authorization": "Bearer abc"},
        "safe": "value",
    }
    sanitized = sanitize_metadata(payload)
    assert sanitized["id_token"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["client_secret"] == "[REDACTED]"
    assert sanitized["nested"]["authorization"] == "[REDACTED]"
    assert sanitized["safe"] == "value"
