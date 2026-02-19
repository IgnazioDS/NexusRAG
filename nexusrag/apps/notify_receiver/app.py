from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import sqlite3
from threading import Lock
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from nexusrag.services.notifications.receiver_contract import (
    ReceiverHeaders,
    SQLiteNotificationDedupeStore,
    parse_required_headers,
    payload_sha256,
    verify_signature,
)


logger = logging.getLogger("nexusrag.notify_receiver")


@dataclass(frozen=True)
class ReceiverSettings:
    # Keep receiver runtime knobs explicit so compose/test environments stay deterministic and inspectable.
    shared_secret: str | None
    require_signature: bool
    require_timestamp: bool
    max_timestamp_skew_seconds: int
    fail_mode: str
    fail_n: int
    port: int
    store_path: str
    store_raw_body: bool


class ReceiverHealth(BaseModel):
    status: str
    require_signature: bool
    require_timestamp: bool
    max_timestamp_skew_seconds: int
    fail_mode: str
    fail_n: int


class ReceiverError(BaseModel):
    accepted: bool = False
    reason: str


class ReceiverWebhookResponse(BaseModel):
    accepted: bool
    duplicate: bool = False
    reason: str | None = None
    notification_id: str | None = None
    payload_sha256: str | None = None


class ReceiptItem(BaseModel):
    id: int
    notification_id: str
    delivery_id: str | None = None
    destination_id: str | None = None
    attempt: int
    tenant_id: str
    event_type: str
    received_at: str
    payload_sha256: str
    header_payload_sha256: str | None = None
    signature_present: int
    signature_valid: int
    response_status: int
    receipt_token: str | None = None
    failure_reason: str | None = None
    duplicate: int


class ReceivedResponse(BaseModel):
    items: list[ReceiptItem]


class ReceiverStats(BaseModel):
    total_requests: int
    accepted_count: int
    failed_count: int
    missing_headers_count: int
    invalid_signature_count: int
    missing_signature_count: int
    signature_misconfig_count: int
    dedupe_hits: int
    duplicates_ratio: float = Field(ge=0.0, le=1.0)
    signature_valid_count: int
    forced_failure_count: int
    last_event_at: str | None = None


class ReceiverOps(BaseModel):
    status: str
    stats: ReceiverStats


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int, *, minimum: int = 0) -> int:
    try:
        parsed = int(value or str(default))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def load_receiver_settings() -> ReceiverSettings:
    # Read receiver config from env so compose and local scripts use one deterministic config surface.
    fail_mode = (os.getenv("RECEIVER_FAIL_MODE") or "never").strip().lower()
    if fail_mode not in {"never", "always", "first_n"}:
        fail_mode = "never"
    return ReceiverSettings(
        shared_secret=(os.getenv("RECEIVER_SHARED_SECRET") or "").strip() or None,
        require_signature=_parse_bool(os.getenv("RECEIVER_REQUIRE_SIGNATURE"), default=False),
        require_timestamp=_parse_bool(os.getenv("RECEIVER_REQUIRE_TIMESTAMP"), default=False),
        max_timestamp_skew_seconds=_parse_int(
            os.getenv("RECEIVER_MAX_TIMESTAMP_SKEW_SECONDS"),
            default=300,
            minimum=1,
        ),
        fail_mode=fail_mode,
        fail_n=_parse_int(os.getenv("RECEIVER_FAIL_N"), default=0, minimum=0),
        port=_parse_int(os.getenv("RECEIVER_PORT"), default=9001, minimum=1),
        store_path=os.getenv("RECEIVER_STORE_PATH", "var/receiver/receiver.db"),
        store_raw_body=_parse_bool(os.getenv("RECEIVER_STORE_RAW_BODY"), default=False),
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _log_event(event: str, **fields: Any) -> None:
    # Emit structured JSON logs so operators can aggregate receiver outcomes without parsing free-form strings.
    payload = {"event": event, **fields, "ts": _utc_now_iso()}
    logger.info(json.dumps(payload, sort_keys=True))


class ReceiverStore:
    # Centralize receiver persistence so receipts/rejections/stats stay transactionally coherent.
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = Lock()
        self._dedupe_store = SQLiteNotificationDedupeStore(db_path=db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            # Persist forced-failure counters per notification id to keep fail_mode=first_n deterministic.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS receiver_fail_counters (
                    notification_id TEXT PRIMARY KEY,
                    failure_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # Persist normalized receipts so ops endpoints can report dedupe and signature verification rates.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS receiver_receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT NOT NULL,
                    delivery_id TEXT,
                    destination_id TEXT,
                    attempt INTEGER NOT NULL,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    header_payload_sha256 TEXT,
                    raw_body TEXT,
                    signature_present INTEGER NOT NULL,
                    signature_valid INTEGER NOT NULL,
                    response_status INTEGER NOT NULL,
                    receipt_token TEXT,
                    failure_reason TEXT,
                    duplicate INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # Keep schema additive for existing local sqlite stores across receiver upgrades.
            for ddl in (
                "ALTER TABLE receiver_receipts ADD COLUMN delivery_id TEXT",
                "ALTER TABLE receiver_receipts ADD COLUMN destination_id TEXT",
                "ALTER TABLE receiver_receipts ADD COLUMN header_payload_sha256 TEXT",
                "ALTER TABLE receiver_receipts ADD COLUMN receipt_token TEXT",
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    # Column already exists on upgraded stores; continue to keep startup idempotent.
                    pass
            # Persist parse-level rejections that may not have a valid notification id for postmortem analysis.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS receiver_rejections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reason TEXT NOT NULL,
                    notification_id TEXT,
                    tenant_id TEXT,
                    event_type TEXT,
                    attempt INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_receiver_receipts_notification_id ON receiver_receipts(notification_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_receiver_receipts_received_at ON receiver_receipts(received_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_receiver_rejections_reason_created ON receiver_rejections(reason, created_at DESC)"
            )
            conn.commit()

    def mark_seen(self, notification_id: str) -> bool:
        # Reuse sqlite-backed dedupe keys so duplicate handling remains safe under concurrent deliveries.
        return self._dedupe_store.mark_seen(notification_id)

    def increment_failure_counter(self, notification_id: str) -> int:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO receiver_fail_counters(notification_id, failure_count)
                VALUES(?, 1)
                ON CONFLICT(notification_id)
                DO UPDATE SET failure_count = failure_count + 1
                """,
                (notification_id,),
            )
            row = conn.execute(
                "SELECT failure_count FROM receiver_fail_counters WHERE notification_id = ?",
                (notification_id,),
            ).fetchone()
            conn.commit()
        return int(row["failure_count"]) if row is not None else 0

    def record_receipt(
        self,
        *,
        headers: ReceiverHeaders,
        payload_digest: str,
        raw_body: str | None,
        signature_present: bool,
        signature_valid: bool,
        response_status: int,
        receipt_token: str | None,
        failure_reason: str | None,
        duplicate: bool,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO receiver_receipts(
                    notification_id,
                    delivery_id,
                    destination_id,
                    attempt,
                    tenant_id,
                    event_type,
                    received_at,
                    payload_sha256,
                    header_payload_sha256,
                    raw_body,
                    signature_present,
                    signature_valid,
                    response_status,
                    receipt_token,
                    failure_reason,
                    duplicate
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    headers.notification_id,
                    headers.delivery_id,
                    headers.destination_id,
                    headers.attempt,
                    headers.tenant_id,
                    headers.event_type,
                    _utc_now_iso(),
                    payload_digest,
                    headers.payload_sha256,
                    raw_body,
                    int(signature_present),
                    int(signature_valid),
                    response_status,
                    receipt_token,
                    failure_reason,
                    int(duplicate),
                ),
            )
            conn.commit()

    def record_rejection(
        self,
        *,
        reason: str,
        notification_id: str | None = None,
        tenant_id: str | None = None,
        event_type: str | None = None,
        attempt: int | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO receiver_rejections(
                    reason,
                    notification_id,
                    tenant_id,
                    event_type,
                    attempt,
                    created_at
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (reason, notification_id, tenant_id, event_type, attempt, _utc_now_iso()),
            )
            conn.commit()

    def list_receipts(self, *, limit: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    notification_id,
                    delivery_id,
                    destination_id,
                    attempt,
                    tenant_id,
                    event_type,
                    received_at,
                    payload_sha256,
                    header_payload_sha256,
                    signature_present,
                    signature_valid,
                    response_status,
                    receipt_token,
                    failure_reason,
                    duplicate
                FROM receiver_receipts
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            totals = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_requests,
                    SUM(CASE WHEN response_status BETWEEN 200 AND 299 THEN 1 ELSE 0 END) AS accepted_count,
                    SUM(CASE WHEN response_status >= 400 THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN duplicate = 1 THEN 1 ELSE 0 END) AS dedupe_hits,
                    SUM(CASE WHEN signature_valid = 1 THEN 1 ELSE 0 END) AS signature_valid_count,
                    SUM(CASE WHEN failure_reason = 'forced_failure' THEN 1 ELSE 0 END) AS forced_failure_count
                FROM receiver_receipts
                """
            ).fetchone()
            missing_headers_count = conn.execute(
                "SELECT COUNT(*) AS c FROM receiver_rejections WHERE reason LIKE 'missing_required_headers%'"
            ).fetchone()["c"]
            invalid_signature_count = conn.execute(
                "SELECT COUNT(*) AS c FROM receiver_receipts WHERE failure_reason IN ('invalid_signature_format','signature_mismatch')"
            ).fetchone()["c"]
            missing_signature_count = conn.execute(
                "SELECT COUNT(*) AS c FROM receiver_receipts WHERE failure_reason = 'missing_signature'"
            ).fetchone()["c"]
            signature_misconfig_count = conn.execute(
                "SELECT COUNT(*) AS c FROM receiver_receipts WHERE failure_reason = 'secret_missing'"
            ).fetchone()["c"]
            latest_row = conn.execute(
                """
                SELECT MAX(ts) AS last_event_at
                FROM (
                    SELECT MAX(received_at) AS ts FROM receiver_receipts
                    UNION ALL
                    SELECT MAX(created_at) AS ts FROM receiver_rejections
                )
                """
            ).fetchone()
        total_requests = int((totals["total_requests"] if totals and totals["total_requests"] else 0) or 0)
        dedupe_hits = int((totals["dedupe_hits"] if totals and totals["dedupe_hits"] else 0) or 0)
        return {
            "total_requests": total_requests,
            "accepted_count": int((totals["accepted_count"] if totals and totals["accepted_count"] else 0) or 0),
            "failed_count": int((totals["failed_count"] if totals and totals["failed_count"] else 0) or 0),
            "missing_headers_count": int(missing_headers_count or 0),
            "invalid_signature_count": int(invalid_signature_count or 0),
            "missing_signature_count": int(missing_signature_count or 0),
            "signature_misconfig_count": int(signature_misconfig_count or 0),
            "dedupe_hits": dedupe_hits,
            "duplicates_ratio": (float(dedupe_hits) / float(total_requests)) if total_requests else 0.0,
            "signature_valid_count": int(
                (totals["signature_valid_count"] if totals and totals["signature_valid_count"] else 0) or 0
            ),
            "forced_failure_count": int(
                (totals["forced_failure_count"] if totals and totals["forced_failure_count"] else 0) or 0
            ),
            "last_event_at": str(latest_row["last_event_at"]) if latest_row and latest_row["last_event_at"] else None,
        }


def _status_for_reason(reason: str) -> int:
    # Map receiver validation reasons to deterministic response classes for sender retry semantics.
    if reason in {"missing_signature", "signature_mismatch", "timestamp_skew"}:
        return 401
    if reason in {"secret_missing"}:
        return 500
    return 400


def _build_receipt_token(
    *,
    notification_id: str,
    delivery_id: str | None,
    payload_sha256_hex: str,
    shared_secret: str | None,
) -> str:
    # Emit deterministic receipt tokens so sender-side receipt persistence can prove receiver acceptance.
    material = f"{notification_id}:{delivery_id or 'none'}:{payload_sha256_hex}".encode("utf-8")
    if shared_secret:
        digest = hmac.new(shared_secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    else:
        digest = hashlib.sha256(material).hexdigest()
    return digest


def _extract_maybe_header(request: Request, header_name: str) -> str | None:
    value = request.headers.get(header_name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def create_app(settings: ReceiverSettings | None = None) -> FastAPI:
    # Build receiver app from explicit settings so in-process and compose modes share the same semantics.
    resolved = settings or load_receiver_settings()
    store = ReceiverStore(resolved.store_path)
    app = FastAPI(
        title="NexusRAG Notification Receiver",
        version="1.0.0",
        description="Reference webhook receiver for Notification Receiver Contract v1.0 validation.",
    )

    @app.get("/health", response_model=ReceiverHealth)
    async def health() -> ReceiverHealth:
        # Expose current receiver mode for deterministic health checks and debugging.
        return ReceiverHealth(
            status="ok",
            require_signature=resolved.require_signature,
            require_timestamp=resolved.require_timestamp,
            max_timestamp_skew_seconds=resolved.max_timestamp_skew_seconds,
            fail_mode=resolved.fail_mode,
            fail_n=resolved.fail_n,
        )

    @app.get("/received", response_model=ReceivedResponse)
    async def received(limit: int = 50) -> ReceivedResponse:
        # Provide bounded receipt listings for local troubleshooting and deterministic E2E assertions.
        return ReceivedResponse(items=[ReceiptItem(**row) for row in store.list_receipts(limit=limit)])

    @app.get("/stats", response_model=ReceiverStats)
    async def stats() -> ReceiverStats:
        # Publish receiver verification counters so operators can spot signature and dedupe regressions quickly.
        return ReceiverStats(**store.stats())

    @app.get("/ops", response_model=ReceiverOps)
    async def ops() -> ReceiverOps:
        # Mirror /stats with an ops envelope for dashboards that expect health + counters in one response.
        return ReceiverOps(status="ok", stats=ReceiverStats(**store.stats()))

    @app.post(
        "/webhook",
        response_model=ReceiverWebhookResponse,
        responses={400: {"model": ReceiverError}, 401: {"model": ReceiverError}, 500: {"model": ReceiverError}},
    )
    async def webhook(request: Request) -> JSONResponse:
        # Parse raw body once so signature hashing and receipt hashing always use identical bytes.
        raw_body = await request.body()
        payload_digest = payload_sha256(raw_body)
        raw_body_text = raw_body.decode("utf-8", errors="replace") if resolved.store_raw_body else None
        try:
            parsed_headers = parse_required_headers(request.headers)
        except ValueError as exc:
            reason = str(exc)
            store.record_rejection(
                reason=reason,
                notification_id=_extract_maybe_header(request, "X-Notification-Id"),
                tenant_id=_extract_maybe_header(request, "X-Notification-Tenant-Id"),
                event_type=_extract_maybe_header(request, "X-Notification-Event-Type"),
            )
            _log_event("receiver.webhook.rejected", reason=reason)
            return JSONResponse(status_code=400, content=ReceiverError(reason=reason).model_dump())

        if resolved.require_timestamp and parsed_headers.timestamp is None:
            reason = "missing_timestamp_header"
            store.record_rejection(
                reason=reason,
                notification_id=parsed_headers.notification_id,
                tenant_id=parsed_headers.tenant_id,
                event_type=parsed_headers.event_type,
                attempt=parsed_headers.attempt,
            )
            store.record_receipt(
                headers=parsed_headers,
                payload_digest=payload_digest,
                raw_body=raw_body_text,
                signature_present=parsed_headers.signature is not None,
                signature_valid=False,
                response_status=400,
                receipt_token=None,
                failure_reason=reason,
                duplicate=False,
            )
            _log_event(
                "receiver.webhook.rejected",
                reason=reason,
                notification_id=parsed_headers.notification_id,
                tenant_id=parsed_headers.tenant_id,
            )
            return JSONResponse(status_code=400, content=ReceiverError(reason=reason).model_dump())

        # Verify signatures for required mode and opportunistically when signatures are present in permissive mode.
        should_verify = resolved.require_signature or parsed_headers.signature is not None
        verification = verify_signature(
            parsed_headers,
            raw_body,
            resolved.shared_secret,
            max_timestamp_skew_seconds=resolved.max_timestamp_skew_seconds,
            now=_utc_now(),
        ) if should_verify else None
        if verification is not None and (resolved.require_signature or not verification.ok):
            if not verification.ok:
                status_code = _status_for_reason(verification.reason)
                store.record_receipt(
                    headers=parsed_headers,
                    payload_digest=payload_digest,
                    raw_body=raw_body_text,
                    signature_present=parsed_headers.signature is not None,
                    signature_valid=False,
                    response_status=status_code,
                    receipt_token=None,
                    failure_reason=verification.reason,
                    duplicate=False,
                )
                _log_event(
                    "receiver.webhook.rejected",
                    reason=verification.reason,
                    notification_id=parsed_headers.notification_id,
                    tenant_id=parsed_headers.tenant_id,
                )
                return JSONResponse(status_code=status_code, content=ReceiverError(reason=verification.reason).model_dump())

        if resolved.fail_mode == "always":
            # Force deterministic 500 responses for retry-path validation.
            store.record_receipt(
                headers=parsed_headers,
                payload_digest=payload_digest,
                raw_body=raw_body_text,
                signature_present=parsed_headers.signature is not None,
                signature_valid=bool(verification.ok if verification else False),
                response_status=500,
                receipt_token=None,
                failure_reason="forced_failure",
                duplicate=False,
            )
            _log_event(
                "receiver.webhook.forced_failure",
                notification_id=parsed_headers.notification_id,
                tenant_id=parsed_headers.tenant_id,
            )
            return JSONResponse(status_code=500, content=ReceiverError(reason="forced_failure").model_dump())

        if resolved.fail_mode == "first_n" and resolved.fail_n > 0:
            failure_count = store.increment_failure_counter(parsed_headers.notification_id)
            if failure_count <= resolved.fail_n:
                store.record_receipt(
                    headers=parsed_headers,
                    payload_digest=payload_digest,
                    raw_body=raw_body_text,
                    signature_present=parsed_headers.signature is not None,
                    signature_valid=bool(verification.ok if verification else False),
                    response_status=500,
                    receipt_token=None,
                    failure_reason="forced_failure",
                    duplicate=False,
                )
                _log_event(
                    "receiver.webhook.forced_failure",
                    notification_id=parsed_headers.notification_id,
                    tenant_id=parsed_headers.tenant_id,
                    failure_count=failure_count,
                )
                return JSONResponse(status_code=500, content=ReceiverError(reason="forced_failure").model_dump())

        dedupe_key = (
            f"{parsed_headers.notification_id}:{parsed_headers.delivery_id}"
            if parsed_headers.delivery_id
            else parsed_headers.notification_id
        )
        receipt_token = _build_receipt_token(
            notification_id=parsed_headers.notification_id,
            delivery_id=parsed_headers.delivery_id,
            payload_sha256_hex=payload_digest,
            shared_secret=resolved.shared_secret,
        )
        is_first_seen = store.mark_seen(dedupe_key)
        if not is_first_seen:
            # Preserve idempotent semantics for redeliveries with the same notification id.
            store.record_receipt(
                headers=parsed_headers,
                payload_digest=payload_digest,
                raw_body=raw_body_text,
                signature_present=parsed_headers.signature is not None,
                signature_valid=bool(verification.ok if verification else False),
                response_status=200,
                receipt_token=receipt_token,
                failure_reason=None,
                duplicate=True,
            )
            _log_event(
                "receiver.webhook.duplicate",
                notification_id=parsed_headers.notification_id,
                tenant_id=parsed_headers.tenant_id,
            )
            return JSONResponse(
                status_code=200,
                headers={
                    "X-Notification-Id": parsed_headers.notification_id,
                    "X-Notification-Receipt": receipt_token,
                },
                content=ReceiverWebhookResponse(
                    accepted=True,
                    duplicate=True,
                    notification_id=parsed_headers.notification_id,
                    payload_sha256=payload_digest,
                ).model_dump(),
            )

        store.record_receipt(
            headers=parsed_headers,
            payload_digest=payload_digest,
            raw_body=raw_body_text,
            signature_present=parsed_headers.signature is not None,
            signature_valid=bool(verification.ok if verification else False),
            response_status=200,
            receipt_token=receipt_token,
            failure_reason=None,
            duplicate=False,
        )
        _log_event(
            "receiver.webhook.accepted",
            notification_id=parsed_headers.notification_id,
            tenant_id=parsed_headers.tenant_id,
            attempt=parsed_headers.attempt,
        )
        return JSONResponse(
            status_code=200,
            headers={
                "X-Notification-Id": parsed_headers.notification_id,
                "X-Notification-Receipt": receipt_token,
            },
            content=ReceiverWebhookResponse(
                accepted=True,
                duplicate=False,
                notification_id=parsed_headers.notification_id,
                payload_sha256=payload_digest,
            ).model_dump(),
        )

    return app
