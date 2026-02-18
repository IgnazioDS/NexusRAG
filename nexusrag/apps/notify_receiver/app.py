from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nexusrag.services.notifications.receiver_contract import (
    compute_payload_sha256_hex,
    verify_signature,
)


@dataclass(frozen=True)
class ReceiverSettings:
    # Keep receiver runtime knobs explicit so compose/test environments stay deterministic.
    shared_secret: str | None
    require_signature: bool
    fail_mode: str
    fail_n: int
    port: int
    store_path: str
    store_raw_body: bool


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_receiver_settings() -> ReceiverSettings:
    # Read receiver config from env so compose and local scripts use the same contract.
    fail_mode = (os.getenv("RECEIVER_FAIL_MODE") or "never").strip().lower()
    if fail_mode not in {"never", "always", "first_n"}:
        fail_mode = "never"
    fail_n_raw = os.getenv("RECEIVER_FAIL_N")
    try:
        fail_n = max(0, int(fail_n_raw or "0"))
    except ValueError:
        fail_n = 0
    return ReceiverSettings(
        shared_secret=(os.getenv("RECEIVER_SHARED_SECRET") or "").strip() or None,
        require_signature=_parse_bool(os.getenv("RECEIVER_REQUIRE_SIGNATURE"), default=False),
        fail_mode=fail_mode,
        fail_n=fail_n,
        port=max(1, int(os.getenv("RECEIVER_PORT", "9001"))),
        store_path=os.getenv("RECEIVER_STORE_PATH", "var/notify_receiver/receiver.db"),
        store_raw_body=_parse_bool(os.getenv("RECEIVER_STORE_RAW_BODY"), default=False),
    )


def _utc_now_iso() -> str:
    # Persist UTC timestamps for stable ordering across multi-container test runs.
    return datetime.now(timezone.utc).isoformat()


class ReceiverStore:
    # Centralize receiver persistence so dedupe/receipts stay consistent across endpoints.
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
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
            # Keep schema minimal and additive for local/e2e contract validation only.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS receiver_seen_notifications (
                    notification_id TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS receiver_fail_counters (
                    notification_id TEXT PRIMARY KEY,
                    failure_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS receiver_receipts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    raw_body TEXT,
                    signature_present INTEGER NOT NULL,
                    signature_valid INTEGER NOT NULL,
                    response_status INTEGER NOT NULL,
                    failure_reason TEXT,
                    duplicate INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_receiver_receipts_notification_id ON receiver_receipts(notification_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_receiver_receipts_received_at ON receiver_receipts(received_at DESC)"
            )
            conn.commit()

    def has_seen(self, notification_id: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM receiver_seen_notifications WHERE notification_id = ?",
                (notification_id,),
            ).fetchone()
        return row is not None

    def mark_seen(self, notification_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO receiver_seen_notifications(notification_id, first_seen_at)
                VALUES(?, ?)
                ON CONFLICT(notification_id) DO NOTHING
                """,
                (notification_id, _utc_now_iso()),
            )
            conn.commit()

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
        notification_id: str,
        attempt: int,
        tenant_id: str,
        event_type: str,
        payload_sha256: str,
        raw_body: str | None,
        signature_present: bool,
        signature_valid: bool,
        response_status: int,
        failure_reason: str | None,
        duplicate: bool,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO receiver_receipts(
                    notification_id,
                    attempt,
                    tenant_id,
                    event_type,
                    received_at,
                    payload_sha256,
                    raw_body,
                    signature_present,
                    signature_valid,
                    response_status,
                    failure_reason,
                    duplicate
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification_id,
                    attempt,
                    tenant_id,
                    event_type,
                    _utc_now_iso(),
                    payload_sha256,
                    raw_body,
                    int(signature_present),
                    int(signature_valid),
                    response_status,
                    failure_reason,
                    int(duplicate),
                ),
            )
            conn.commit()

    def list_receipts(self, *, limit: int) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    notification_id,
                    attempt,
                    tenant_id,
                    event_type,
                    received_at,
                    payload_sha256,
                    signature_present,
                    signature_valid,
                    response_status,
                    failure_reason,
                    duplicate
                FROM receiver_receipts
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        return [dict(row) for row in rows]


def create_app(settings: ReceiverSettings | None = None) -> FastAPI:
    # Build receiver app from explicit settings to keep in-process tests deterministic.
    resolved = settings or load_receiver_settings()
    store = ReceiverStore(resolved.store_path)
    app = FastAPI(title="NexusRAG Notification Receiver")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        # Expose config-derived health state for compose readiness checks.
        return {
            "status": "ok",
            "require_signature": resolved.require_signature,
            "fail_mode": resolved.fail_mode,
            "fail_n": resolved.fail_n,
        }

    @app.get("/received")
    async def received(limit: int = 50) -> dict[str, Any]:
        # Provide bounded receipt listings for local troubleshooting and deterministic E2E assertions.
        return {"items": store.list_receipts(limit=limit)}

    @app.post("/webhook")
    async def webhook(request: Request) -> JSONResponse:
        # Validate required transport headers before any side effects so sender errors are explicit.
        notification_id = request.headers.get("X-Notification-Id")
        attempt_header = request.headers.get("X-Notification-Attempt")
        event_type = request.headers.get("X-Notification-Event-Type")
        tenant_id = request.headers.get("X-Notification-Tenant-Id")
        signature_header = request.headers.get("X-Notification-Signature")
        if not notification_id or not attempt_header or not event_type or not tenant_id:
            return JSONResponse(
                status_code=400,
                content={"accepted": False, "reason": "missing_required_headers"},
            )
        try:
            attempt = max(1, int(attempt_header))
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"accepted": False, "reason": "invalid_attempt_header"},
            )

        raw_body = await request.body()
        payload_sha256 = compute_payload_sha256_hex(raw_body)
        raw_body_text = raw_body.decode("utf-8", errors="replace") if resolved.store_raw_body else None
        signature_present = bool(signature_header)
        signature_valid = False

        if resolved.require_signature and resolved.shared_secret:
            # Enforce signature validation only when configured so local non-signed testing remains possible.
            signature_valid, reason = verify_signature(resolved.shared_secret, raw_body, signature_header)
            if not signature_valid:
                status_code = 401 if reason in {"missing_signature", "signature_mismatch"} else 400
                store.record_receipt(
                    notification_id=notification_id,
                    attempt=attempt,
                    tenant_id=tenant_id,
                    event_type=event_type,
                    payload_sha256=payload_sha256,
                    raw_body=raw_body_text,
                    signature_present=signature_present,
                    signature_valid=False,
                    response_status=status_code,
                    failure_reason=reason,
                    duplicate=False,
                )
                return JSONResponse(status_code=status_code, content={"accepted": False, "reason": reason})
        elif signature_present and resolved.shared_secret:
            # Validate opportunistically when signatures are provided but not required for this receiver mode.
            signature_valid, _reason = verify_signature(resolved.shared_secret, raw_body, signature_header)

        if store.has_seen(notification_id):
            # Preserve receiver idempotency semantics by returning 200 for duplicate notification IDs.
            store.record_receipt(
                notification_id=notification_id,
                attempt=attempt,
                tenant_id=tenant_id,
                event_type=event_type,
                payload_sha256=payload_sha256,
                raw_body=raw_body_text,
                signature_present=signature_present,
                signature_valid=signature_valid,
                response_status=200,
                failure_reason=None,
                duplicate=True,
            )
            return JSONResponse(status_code=200, content={"accepted": True, "duplicate": True})

        if resolved.fail_mode == "always":
            store.record_receipt(
                notification_id=notification_id,
                attempt=attempt,
                tenant_id=tenant_id,
                event_type=event_type,
                payload_sha256=payload_sha256,
                raw_body=raw_body_text,
                signature_present=signature_present,
                signature_valid=signature_valid,
                response_status=500,
                failure_reason="forced_failure",
                duplicate=False,
            )
            return JSONResponse(status_code=500, content={"accepted": False, "reason": "forced_failure"})

        if resolved.fail_mode == "first_n" and resolved.fail_n > 0:
            failure_count = store.increment_failure_counter(notification_id)
            if failure_count <= resolved.fail_n:
                # Fail deterministically for first N attempts per notification id to exercise sender retry logic.
                store.record_receipt(
                    notification_id=notification_id,
                    attempt=attempt,
                    tenant_id=tenant_id,
                    event_type=event_type,
                    payload_sha256=payload_sha256,
                    raw_body=raw_body_text,
                    signature_present=signature_present,
                    signature_valid=signature_valid,
                    response_status=500,
                    failure_reason="forced_failure",
                    duplicate=False,
                )
                return JSONResponse(status_code=500, content={"accepted": False, "reason": "forced_failure"})

        store.mark_seen(notification_id)
        store.record_receipt(
            notification_id=notification_id,
            attempt=attempt,
            tenant_id=tenant_id,
            event_type=event_type,
            payload_sha256=payload_sha256,
            raw_body=raw_body_text,
            signature_present=signature_present,
            signature_valid=signature_valid if signature_present else False,
            response_status=200,
            failure_reason=None,
            duplicate=False,
        )
        return JSONResponse(status_code=200, content={"accepted": True, "duplicate": False})

    return app

