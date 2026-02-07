from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from nexusrag.domain.models import AuditEvent
from nexusrag.persistence.db import SessionLocal


logger = logging.getLogger(__name__)

_SENSITIVE_KEY_PATTERNS = ["api_key", "authorization", "token", "secret", "password", "text", "content"]
_REDACTED_VALUE = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    # Match sensitive key fragments case-insensitively to enforce redaction policy.
    lowered = key.lower()
    return any(pattern in lowered for pattern in _SENSITIVE_KEY_PATTERNS)


def sanitize_metadata(value: Any) -> Any:
    # Recursively scrub sensitive fields while preserving safe structure.
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _is_sensitive_key(key):
                sanitized[key] = _REDACTED_VALUE
            else:
                sanitized[key] = sanitize_metadata(raw_value)
        return sanitized
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    return value


def get_request_context(request: Request | None) -> dict[str, str | None]:
    # Extract request identifiers and client hints without persisting credentials.
    if request is None:
        return {"request_id": None, "ip_address": None, "user_agent": None}
    request_id = request.headers.get("X-Request-Id")
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return {"request_id": request_id, "ip_address": ip_address, "user_agent": user_agent}


async def record_event(
    *,
    session: AsyncSession | None = None,
    occurred_at: datetime | None = None,
    tenant_id: str | None,
    actor_type: str,
    actor_id: str | None,
    actor_role: str | None,
    event_type: str,
    outcome: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
    error_code: str | None = None,
    commit: bool | None = None,
    best_effort: bool = True,
) -> None:
    # Write audit rows in a best-effort manner to avoid breaking user flows.
    sanitized_metadata = sanitize_metadata(metadata or {})
    event = AuditEvent(
        occurred_at=occurred_at or datetime.now(timezone.utc),
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_role=actor_role,
        event_type=event_type,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_json=sanitized_metadata,
        error_code=error_code,
    )

    if session is None:
        async with SessionLocal() as audit_session:
            try:
                audit_session.add(event)
                await audit_session.commit()
            except SQLAlchemyError as exc:
                await audit_session.rollback()
                level = logger.warning if best_effort else logger.error
                level(
                    "audit_event_write_failed event_type=%s request_id=%s",
                    event_type,
                    request_id,
                    exc_info=exc,
                )
        return

    resolved_commit = commit if commit is not None else False
    try:
        session.add(event)
        if resolved_commit:
            await session.commit()
    except SQLAlchemyError as exc:
        if resolved_commit:
            await session.rollback()
        level = logger.warning if best_effort else logger.error
        level(
            "audit_event_write_failed event_type=%s request_id=%s",
            event_type,
            request_id,
            exc_info=exc,
        )
