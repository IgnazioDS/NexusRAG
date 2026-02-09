from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import time
import logging
from typing import Any

import httpx

from nexusrag.core.config import get_settings
from nexusrag.services.audit import record_system_event
from nexusrag.services.resilience import CircuitBreaker, get_resilience_redis, retry_async
from nexusrag.services.telemetry import record_external_call


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookDeliveryResult:
    # Summarize webhook delivery attempts for API responses and auditing.
    sent: bool
    status_code: int | None
    message: str


def build_billing_signature(secret: str, payload: bytes) -> str:
    # Compute HMAC SHA256 signatures for billing webhook payloads.
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


async def send_billing_webhook_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    require_enabled: bool = True,
) -> WebhookDeliveryResult:
    # Send signed billing webhook payloads with a short timeout and safe failure mode.
    settings = get_settings()
    if require_enabled and not settings.billing_webhook_enabled:
        return WebhookDeliveryResult(
            sent=False,
            status_code=None,
            message="Billing webhook is disabled",
        )
    if not settings.billing_webhook_url or not settings.billing_webhook_secret:
        return WebhookDeliveryResult(
            sent=False,
            status_code=None,
            message="Billing webhook is not configured",
        )

    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = build_billing_signature(settings.billing_webhook_secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-Billing-Signature": signature,
        "X-Billing-Event": event_type,
    }
    timeout = min(settings.billing_webhook_timeout_ms, settings.ext_call_timeout_ms) / 1000.0

    breaker: CircuitBreaker | None = None
    start = time.monotonic()
    try:
        redis = await get_resilience_redis()

        async def _on_transition(name: str, state: str) -> None:
            await record_system_event(
                event_type=f"system.circuit_breaker.{state}",
                metadata={"integration": name},
            )

        breaker = CircuitBreaker(
            "billing.webhook",
            redis=redis,
            on_transition=_on_transition,
        )
        await breaker.before_call()

        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.post(settings.billing_webhook_url, content=body, headers=headers)

        def _retryable(exc: Exception) -> bool:
            if isinstance(exc, httpx.TimeoutException):
                return True
            if isinstance(exc, httpx.NetworkError):
                return True
            status = getattr(exc, "status_code", None)
            return isinstance(status, int) and status >= 500

        response = await retry_async(_call, retryable=_retryable)
    except Exception as exc:  # noqa: BLE001 - webhook failures are non-fatal
        if breaker is not None:
            try:
                await breaker.record_failure()
            except Exception:
                pass
        record_external_call(
            integration="billing.webhook",
            latency_ms=(time.monotonic() - start) * 1000.0,
            success=False,
        )
        logger.warning("billing_webhook_send_failed event_type=%s", event_type, exc_info=exc)
        return WebhookDeliveryResult(sent=False, status_code=None, message=str(exc))

    if response.status_code >= 400:
        if response.status_code >= 500:
            if breaker is not None:
                await breaker.record_failure()
        record_external_call(
            integration="billing.webhook",
            latency_ms=(time.monotonic() - start) * 1000.0,
            success=False,
        )
        return WebhookDeliveryResult(
            sent=False,
            status_code=response.status_code,
            message=f"Webhook responded with status {response.status_code}",
        )

    if breaker is not None:
        await breaker.record_success()
    record_external_call(
        integration="billing.webhook",
        latency_ms=(time.monotonic() - start) * 1000.0,
        success=True,
    )
    return WebhookDeliveryResult(
        sent=True,
        status_code=response.status_code,
        message="Webhook delivered successfully",
    )
