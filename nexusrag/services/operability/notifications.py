from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.services.audit import record_event
from nexusrag.services.entitlements import FEATURE_OPS_ADMIN, get_effective_entitlements


async def send_operability_notification(
    *,
    session: AsyncSession,
    tenant_id: str | None,
    event_type: str,
    payload: dict[str, Any],
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> None:
    # Keep notification delivery best-effort so alert/incident flows never block on adapters.
    settings = get_settings()
    if tenant_id is not None:
        # Respect ops entitlements so notification adapters stay plan-gated like other operator features.
        entitlements = await get_effective_entitlements(session, tenant_id)
        entitlement = entitlements.get(FEATURE_OPS_ADMIN)
        if entitlement is None or not entitlement.enabled:
            return
    adapter = settings.ops_notification_adapter.strip().lower()
    if adapter == "noop":
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="notification.sent",
            outcome="success",
            resource_type="notification",
            resource_id=event_type,
            request_id=request_id,
            metadata={"adapter": "noop"},
            commit=True,
            best_effort=True,
        )
        return

    if adapter != "webhook" or not settings.ops_notification_webhook_url:
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="notification.failed",
            outcome="failure",
            resource_type="notification",
            resource_id=event_type,
            request_id=request_id,
            metadata={"adapter": adapter, "reason": "adapter_unconfigured"},
            commit=True,
            best_effort=True,
        )
        return

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.post(
                settings.ops_notification_webhook_url,
                json={
                    "event_type": event_type,
                    "tenant_id": tenant_id,
                    "payload": payload,
                },
            )
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - keep adapter failures isolated from control plane.
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="system",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="notification.failed",
            outcome="failure",
            resource_type="notification",
            resource_id=event_type,
            request_id=request_id,
            metadata={"adapter": "webhook", "error": str(exc)},
            commit=True,
            best_effort=True,
        )
        return

    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="system",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="notification.sent",
        outcome="success",
        resource_type="notification",
        resource_id=event_type,
        request_id=request_id,
        metadata={"adapter": "webhook"},
        commit=True,
        best_effort=True,
    )
