from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Mapping, Protocol


_HEADER_NOTIFICATION_ID = "x-notification-id"
_HEADER_NOTIFICATION_ATTEMPT = "x-notification-attempt"
_HEADER_NOTIFICATION_EVENT_TYPE = "x-notification-event-type"
_HEADER_NOTIFICATION_TENANT_ID = "x-notification-tenant-id"
_HEADER_NOTIFICATION_SIGNATURE = "x-notification-signature"
_HEADER_NOTIFICATION_TIMESTAMP = "x-notification-timestamp"


@dataclass(frozen=True)
class ParsedSignature:
    # Keep parsed signature shape explicit so sender and receivers share one canonical schema.
    algorithm: str
    digest_hex: str


@dataclass(frozen=True)
class ReceiverHeaders:
    # Capture the normalized transport headers required by the receiver contract.
    notification_id: str
    attempt: int
    event_type: str
    tenant_id: str
    signature: str | None
    timestamp: datetime | None


@dataclass(frozen=True)
class VerificationResult:
    # Return rich verification output so operators can diagnose failures without inspecting payload secrets.
    ok: bool
    reason: str
    payload_sha256: str
    algorithm: str | None = None
    expected_signature: str | None = None
    provided_signature: str | None = None


class NotificationDedupeStore(Protocol):
    # Define one dedupe contract reusable across tests and persistent receiver implementations.
    def has_seen(self, notification_id: str) -> bool: ...

    def mark_seen(self, notification_id: str) -> bool: ...


class InMemoryNotificationDedupeStore:
    # Keep a thread-safe in-memory dedupe implementation for deterministic tests and lightweight usage.
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._lock = Lock()

    def has_seen(self, notification_id: str) -> bool:
        with self._lock:
            return notification_id in self._seen

    def mark_seen(self, notification_id: str) -> bool:
        # Return whether we observed this notification id for the first time.
        with self._lock:
            if notification_id in self._seen:
                return False
            self._seen.add(notification_id)
            return True


class SQLiteNotificationDedupeStore:
    # Persist dedupe keys in sqlite so local receiver restarts preserve idempotency guarantees.
    def __init__(self, db_path: str, table_name: str = "receiver_seen_notifications") -> None:
        self._db_path = db_path
        self._table_name = table_name
        self._lock = Lock()
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    notification_id TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS ix_{self._table_name}_first_seen_at ON {self._table_name}(first_seen_at)"
            )
            conn.commit()

    def has_seen(self, notification_id: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {self._table_name} WHERE notification_id = ?",
                (notification_id,),
            ).fetchone()
        return row is not None

    def mark_seen(self, notification_id: str) -> bool:
        # Perform atomic insert-or-ignore so concurrent duplicate deliveries cannot double-process.
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                f"""
                INSERT INTO {self._table_name}(notification_id, first_seen_at)
                VALUES(?, ?)
                ON CONFLICT(notification_id) DO NOTHING
                """,
                (notification_id, _utc_now_iso()),
            )
            conn.commit()
            return int(cursor.rowcount or 0) == 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_header_mapping(headers: Mapping[str, str] | Mapping[str, object]) -> dict[str, str]:
    # Normalize header keys to lower-case and strip values for strict parsing behavior.
    normalized: dict[str, str] = {}
    for raw_key, raw_value in headers.items():
        key = str(raw_key).strip().lower()
        if not key:
            continue
        value = str(raw_value).strip()
        normalized[key] = value
    return normalized


def parse_signature(header_value: str) -> ParsedSignature:
    # Parse `sha256=<hex>` signatures strictly so malformed values are rejected deterministically.
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
    except ValueError as exc:  # pragma: no cover - conversion error path is explicit.
        raise ValueError("invalid_signature_format") from exc
    if len(digest_hex) != 64:
        raise ValueError("invalid_signature_format")
    return ParsedSignature(algorithm=normalized_algorithm, digest_hex=digest_hex)


def parse_required_headers(headers: Mapping[str, str] | Mapping[str, object]) -> ReceiverHeaders:
    # Parse required receiver headers in one place so all receiver implementations share strict semantics.
    normalized = _normalize_header_mapping(headers)
    missing = [
        header_name
        for header_name in (
            _HEADER_NOTIFICATION_ID,
            _HEADER_NOTIFICATION_ATTEMPT,
            _HEADER_NOTIFICATION_EVENT_TYPE,
            _HEADER_NOTIFICATION_TENANT_ID,
        )
        if not normalized.get(header_name)
    ]
    if missing:
        raise ValueError(f"missing_required_headers:{','.join(missing)}")
    try:
        attempt = int(normalized[_HEADER_NOTIFICATION_ATTEMPT])
    except ValueError as exc:
        raise ValueError("invalid_attempt_header") from exc
    if attempt < 1:
        raise ValueError("invalid_attempt_header")
    raw_timestamp = normalized.get(_HEADER_NOTIFICATION_TIMESTAMP)
    parsed_timestamp: datetime | None = None
    if raw_timestamp:
        try:
            parsed_timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            if parsed_timestamp.tzinfo is None:
                parsed_timestamp = parsed_timestamp.replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ValueError("invalid_timestamp_header") from exc
    return ReceiverHeaders(
        notification_id=normalized[_HEADER_NOTIFICATION_ID],
        attempt=attempt,
        event_type=normalized[_HEADER_NOTIFICATION_EVENT_TYPE],
        tenant_id=normalized[_HEADER_NOTIFICATION_TENANT_ID],
        signature=normalized.get(_HEADER_NOTIFICATION_SIGNATURE) or None,
        timestamp=parsed_timestamp,
    )


def compute_hmac_sha256_hex(secret: str, raw_body_bytes: bytes) -> str:
    # Compute HMAC over raw bytes only so signatures remain canonical across sender and receivers.
    return hmac.new(secret.encode("utf-8"), raw_body_bytes, hashlib.sha256).hexdigest()


def compute_signature(raw_body: bytes, secret: str) -> str:
    # Return canonical signature header value so receiver quickstarts can copy one helper directly.
    return f"sha256={compute_hmac_sha256_hex(secret, raw_body)}"


def payload_sha256(raw_body: bytes) -> str:
    # Hash exact raw payload bytes for immutable outbound/inbound integrity comparisons.
    return hashlib.sha256(raw_body).hexdigest()


def compute_payload_sha256_hex(raw_body_bytes: bytes) -> str:
    # Keep backward-compatible alias for existing call sites while the v1 API uses payload_sha256().
    return payload_sha256(raw_body_bytes)


def verify_signature(
    headers: ReceiverHeaders | Mapping[str, str] | Mapping[str, object],
    raw_body: bytes,
    secret: str | None,
    *,
    max_timestamp_skew_seconds: int | None = None,
    now: datetime | None = None,
) -> VerificationResult:
    # Verify signature and optional timestamp skew with stable reason codes for deterministic operations.
    parsed_headers = headers if isinstance(headers, ReceiverHeaders) else parse_required_headers(headers)
    payload_digest = payload_sha256(raw_body)
    signature_header = parsed_headers.signature
    if not secret:
        if signature_header:
            return VerificationResult(
                ok=False,
                reason="secret_missing",
                payload_sha256=payload_digest,
                provided_signature=signature_header,
            )
        return VerificationResult(ok=True, reason="unsigned_allowed", payload_sha256=payload_digest)
    if not signature_header:
        return VerificationResult(ok=False, reason="missing_signature", payload_sha256=payload_digest)
    try:
        parsed_signature = parse_signature(signature_header)
    except ValueError:
        return VerificationResult(
            ok=False,
            reason="invalid_signature_format",
            payload_sha256=payload_digest,
            provided_signature=signature_header,
        )
    expected_hex = compute_hmac_sha256_hex(secret, raw_body)
    if not hmac.compare_digest(expected_hex, parsed_signature.digest_hex):
        return VerificationResult(
            ok=False,
            reason="signature_mismatch",
            payload_sha256=payload_digest,
            algorithm=parsed_signature.algorithm,
            expected_signature=expected_hex,
            provided_signature=parsed_signature.digest_hex,
        )
    if max_timestamp_skew_seconds is not None and max_timestamp_skew_seconds > 0 and parsed_headers.timestamp is not None:
        reference_time = now or datetime.now(timezone.utc)
        skew_seconds = abs((reference_time - parsed_headers.timestamp).total_seconds())
        if skew_seconds > max_timestamp_skew_seconds:
            return VerificationResult(
                ok=False,
                reason="timestamp_skew",
                payload_sha256=payload_digest,
                algorithm=parsed_signature.algorithm,
                expected_signature=expected_hex,
                provided_signature=parsed_signature.digest_hex,
            )
    return VerificationResult(
        ok=True,
        reason="ok",
        payload_sha256=payload_digest,
        algorithm=parsed_signature.algorithm,
        expected_signature=expected_hex,
        provided_signature=parsed_signature.digest_hex,
    )


def verify_signature_legacy(secret: str, raw_body_bytes: bytes, header_value: str | None) -> tuple[bool, str]:
    # Preserve old helper behavior for compatibility with existing tests/imports during v1 migration.
    headers = ReceiverHeaders(
        notification_id="legacy",
        attempt=1,
        event_type="legacy",
        tenant_id="legacy",
        signature=header_value,
        timestamp=None,
    )
    result = verify_signature(headers, raw_body_bytes, secret)
    return result.ok, result.reason

