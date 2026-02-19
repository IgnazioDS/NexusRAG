from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from typing import Protocol


@dataclass(frozen=True)
class ParsedSignature:
    # Keep parsed signature structure explicit so verifier and receivers share one canonical shape.
    algorithm: str
    digest_hex: str


class NotificationDedupeStore(Protocol):
    # Define one minimal dedupe contract reusable across in-memory tests and persistent receiver implementations.
    def has_seen(self, notification_id: str) -> bool: ...

    def mark_seen(self, notification_id: str) -> None: ...


class InMemoryNotificationDedupeStore:
    # Keep an in-memory dedupe implementation for deterministic unit tests and local prototyping.
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def has_seen(self, notification_id: str) -> bool:
        return notification_id in self._seen

    def mark_seen(self, notification_id: str) -> None:
        self._seen.add(notification_id)


def parse_signature(header_value: str) -> ParsedSignature:
    # Parse `algo=hex` signature headers with strict validation to keep receiver behavior deterministic.
    raw = header_value.strip()
    algorithm, separator, digest = raw.partition("=")
    if separator != "=":
        raise ValueError("invalid_signature_format")
    normalized_algorithm = algorithm.strip().lower()
    digest_hex = digest.strip().lower()
    if normalized_algorithm != "sha256":
        raise ValueError("invalid_signature_format")
    if not digest_hex:
        raise ValueError("invalid_signature_format")
    try:
        int(digest_hex, 16)
    except ValueError as exc:  # pragma: no cover - explicit conversion error path.
        raise ValueError("invalid_signature_format") from exc
    if len(digest_hex) != 64:
        raise ValueError("invalid_signature_format")
    return ParsedSignature(algorithm=normalized_algorithm, digest_hex=digest_hex)


def compute_hmac_sha256_hex(secret: str, raw_body_bytes: bytes) -> str:
    # Compute HMAC over raw body bytes only so sender and receiver operate on identical signed content.
    digest = hmac.new(secret.encode("utf-8"), raw_body_bytes, hashlib.sha256).hexdigest()
    return digest


def verify_signature(secret: str, raw_body_bytes: bytes, header_value: str | None) -> tuple[bool, str]:
    # Return explicit failure reasons so receivers can expose deterministic diagnostics for operators.
    if not header_value:
        return False, "missing_signature"
    try:
        parsed = parse_signature(header_value)
    except ValueError:
        return False, "invalid_signature_format"
    expected = compute_hmac_sha256_hex(secret, raw_body_bytes)
    if not hmac.compare_digest(expected, parsed.digest_hex):
        return False, "signature_mismatch"
    return True, "ok"


def compute_payload_sha256_hex(raw_body_bytes: bytes) -> str:
    # Hash raw payload bytes exactly as transmitted so forensic checks remain sender/receiver consistent.
    return hashlib.sha256(raw_body_bytes).hexdigest()

