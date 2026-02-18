from __future__ import annotations

from nexusrag.services.notifications.receiver_contract import (
    InMemoryNotificationDedupeStore,
    compute_hmac_sha256_hex,
    compute_payload_sha256_hex,
    parse_signature,
    verify_signature,
)


def test_signature_helpers_round_trip() -> None:
    # Verify hash/signature helpers stay byte-accurate for stable sender/receiver contract validation.
    body = b'{"event":"incident.opened","severity":"high"}'
    secret = "super-secret"
    digest = compute_hmac_sha256_hex(secret, body)
    parsed = parse_signature(f"sha256={digest}")
    assert parsed.algorithm == "sha256"
    assert parsed.digest_hex == digest
    ok, reason = verify_signature(secret, body, f"sha256={digest}")
    assert ok is True
    assert reason == "ok"


def test_signature_verification_failures_are_explicit() -> None:
    # Keep verifier reason codes deterministic so receiver APIs can expose stable failure diagnostics.
    body = b"payload"
    secret = "super-secret"
    ok, reason = verify_signature(secret, body, None)
    assert ok is False
    assert reason == "missing_signature"

    ok, reason = verify_signature(secret, body, "sha256-not-valid")
    assert ok is False
    assert reason == "invalid_signature_format"

    ok, reason = verify_signature(secret, body, "sha256=" + ("00" * 32))
    assert ok is False
    assert reason == "signature_mismatch"


def test_payload_hash_and_dedupe_store() -> None:
    # Ensure dedupe primitives and payload hash are deterministic for receiver idempotency behavior.
    body = b"payload"
    assert compute_payload_sha256_hex(body) == compute_payload_sha256_hex(body)
    store = InMemoryNotificationDedupeStore()
    assert store.has_seen("n-1") is False
    store.mark_seen("n-1")
    assert store.has_seen("n-1") is True

