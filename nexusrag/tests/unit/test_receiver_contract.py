from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import pytest

from nexusrag.services.notifications.receiver_contract import (
    InMemoryNotificationDedupeStore,
    SQLiteNotificationDedupeStore,
    compute_signature,
    parse_required_headers,
    parse_signature,
    payload_sha256,
    verify_signature,
)


def test_signature_helpers_round_trip() -> None:
    # Verify signature helpers stay byte-accurate for stable sender/receiver contract validation.
    body = b'{"event":"incident.opened","severity":"high"}'
    secret = "super-secret"
    signature_header = compute_signature(body, secret)
    parsed = parse_signature(signature_header)
    assert parsed.algorithm == "sha256"
    assert len(parsed.digest_hex) == 64
    headers = parse_required_headers(
        {
            "X-Notification-Id": "n-1",
            "X-Notification-Attempt": "1",
            "X-Notification-Event-Type": "incident.opened",
            "X-Notification-Tenant-Id": "t1",
            "X-Notification-Signature": signature_header,
        }
    )
    verification = verify_signature(headers, body, secret)
    assert verification.ok is True
    assert verification.reason == "ok"
    assert verification.payload_sha256 == payload_sha256(body)


@pytest.mark.parametrize(
    ("raw_headers", "expected_reason"),
    [
        ({}, "missing_required_headers:x-notification-id,x-notification-attempt,x-notification-event-type,x-notification-tenant-id"),
        (
            {
                "X-Notification-Id": "n-1",
                "X-Notification-Attempt": "NaN",
                "X-Notification-Event-Type": "incident.opened",
                "X-Notification-Tenant-Id": "t1",
            },
            "invalid_attempt_header",
        ),
        (
            {
                "X-Notification-Id": "n-1",
                "X-Notification-Attempt": "0",
                "X-Notification-Event-Type": "incident.opened",
                "X-Notification-Tenant-Id": "t1",
            },
            "invalid_attempt_header",
        ),
        (
            {
                "X-Notification-Id": "n-1",
                "X-Notification-Attempt": "1",
                "X-Notification-Event-Type": "incident.opened",
                "X-Notification-Tenant-Id": "t1",
                "X-Notification-Timestamp": "not-a-timestamp",
            },
            "invalid_timestamp_header",
        ),
    ],
)
def test_parse_required_headers_edge_cases(raw_headers: dict[str, str], expected_reason: str) -> None:
    # Keep strict parse failures explicit so receivers can map malformed requests deterministically.
    with pytest.raises(ValueError, match=expected_reason):
        parse_required_headers(raw_headers)


def test_parse_required_headers_normalizes_case_and_whitespace() -> None:
    # Accept case/whitespace variants because common proxies normalize header casing unpredictably.
    parsed = parse_required_headers(
        {
            "x-notification-id": "  n-2  ",
            "X-NOTIFICATION-ATTEMPT": " 3 ",
            "x-notification-event-type": " incident.resolved ",
            "X-Notification-Tenant-Id": " tenant-a ",
            "X-Notification-Signature": " sha256=" + ("0" * 64) + " ",
        }
    )
    assert parsed.notification_id == "n-2"
    assert parsed.attempt == 3
    assert parsed.event_type == "incident.resolved"
    assert parsed.tenant_id == "tenant-a"
    assert parsed.signature == "sha256=" + ("0" * 64)


def test_signature_verification_reasons() -> None:
    # Ensure verifier reason codes remain stable so sender/receiver incident triage is predictable.
    body = b"payload"
    headers = parse_required_headers(
        {
            "X-Notification-Id": "n-1",
            "X-Notification-Attempt": "1",
            "X-Notification-Event-Type": "incident.opened",
            "X-Notification-Tenant-Id": "t1",
        }
    )
    missing = verify_signature(headers, body, "secret")
    assert missing.ok is False
    assert missing.reason == "missing_signature"

    malformed_headers = parse_required_headers(
        {
            "X-Notification-Id": "n-1",
            "X-Notification-Attempt": "1",
            "X-Notification-Event-Type": "incident.opened",
            "X-Notification-Tenant-Id": "t1",
            "X-Notification-Signature": "sha256-not-valid",
        }
    )
    malformed = verify_signature(malformed_headers, body, "secret")
    assert malformed.ok is False
    assert malformed.reason == "invalid_signature_format"

    mismatch_headers = parse_required_headers(
        {
            "X-Notification-Id": "n-1",
            "X-Notification-Attempt": "1",
            "X-Notification-Event-Type": "incident.opened",
            "X-Notification-Tenant-Id": "t1",
            "X-Notification-Signature": "sha256=" + ("00" * 32),
        }
    )
    mismatch = verify_signature(mismatch_headers, body, "secret")
    assert mismatch.ok is False
    assert mismatch.reason == "signature_mismatch"

    secret_missing = verify_signature(mismatch_headers, body, None)
    assert secret_missing.ok is False
    assert secret_missing.reason == "secret_missing"


def test_signature_timestamp_skew_tolerance() -> None:
    # Apply skew checks only when timestamp is present to support optional timestamp rollout contracts.
    now = datetime.now(timezone.utc)
    body = json.dumps({"hello": "world"}).encode("utf-8")
    signature_header = compute_signature(body, "secret")
    old_timestamp = (now - timedelta(minutes=20)).isoformat()
    headers = parse_required_headers(
        {
            "X-Notification-Id": "n-time",
            "X-Notification-Attempt": "1",
            "X-Notification-Event-Type": "incident.opened",
            "X-Notification-Tenant-Id": "t1",
            "X-Notification-Signature": signature_header,
            "X-Notification-Timestamp": old_timestamp,
        }
    )
    result = verify_signature(headers, body, "secret", max_timestamp_skew_seconds=300, now=now)
    assert result.ok is False
    assert result.reason == "timestamp_skew"


def test_inmemory_dedupe_store_contract() -> None:
    # Confirm in-memory dedupe helpers preserve idempotency semantics for tests/prototypes.
    store = InMemoryNotificationDedupeStore()
    assert store.has_seen("n-1") is False
    assert store.mark_seen("n-1") is True
    assert store.has_seen("n-1") is True
    assert store.mark_seen("n-1") is False


def test_sqlite_dedupe_store_is_concurrency_safe(tmp_path: Path) -> None:
    # Ensure sqlite dedupe mark_seen() remains atomic under concurrent duplicate deliveries.
    db_path = str(tmp_path / "dedupe.db")
    store = SQLiteNotificationDedupeStore(db_path=db_path)

    def _mark() -> bool:
        return store.mark_seen("n-concurrent")

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _idx: _mark(), range(64)))

    assert sum(1 for item in results if item) == 1
    assert store.has_seen("n-concurrent") is True

