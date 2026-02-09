from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from nexusrag.core.config import get_settings


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
    timeout = settings.billing_webhook_timeout_ms / 1000.0

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(settings.billing_webhook_url, content=body, headers=headers)
    except Exception as exc:  # noqa: BLE001 - webhook failures are non-fatal
        logger.warning("billing_webhook_send_failed event_type=%s", event_type, exc_info=exc)
        return WebhookDeliveryResult(sent=False, status_code=None, message=str(exc))

    if response.status_code >= 400:
        return WebhookDeliveryResult(
            sent=False,
            status_code=response.status_code,
            message=f"Webhook responded with status {response.status_code}",
        )

    return WebhookDeliveryResult(
        sent=True,
        status_code=response.status_code,
        message="Webhook delivered successfully",
    )
