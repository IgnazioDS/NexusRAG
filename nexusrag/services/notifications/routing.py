from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import NotificationDestination, NotificationRoute

_ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class ResolvedNotificationDestination:
    # Return destination ids and route provenance so enqueue/audit paths stay deterministic and auditable.
    destination_id: str | None
    destination_url: str
    route_id: str | None
    source: str


def _normalize_match_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip())
        return normalized
    return []


def _matches_filter(*, configured: Any, actual: str | None, wildcard: bool = False) -> bool:
    values = _normalize_match_value(configured)
    if not values:
        return True
    if actual is None:
        return False
    lowered = actual.strip().lower()
    for value in values:
        candidate = value.lower()
        if wildcard and candidate == "*":
            return True
        if candidate == lowered:
            return True
    return False


def _matches_route(
    *,
    route: NotificationRoute,
    event_type: str,
    severity: str,
    source: str | None,
    category: str | None,
) -> bool:
    # Treat missing match keys as wildcards so routes can target only selected dimensions.
    match_json = route.match_json or {}
    if not isinstance(match_json, dict):
        return False
    if not _matches_filter(configured=match_json.get("event_type"), actual=event_type, wildcard=True):
        return False
    if not _matches_filter(configured=match_json.get("severity"), actual=severity):
        return False
    if not _matches_filter(configured=match_json.get("source"), actual=source):
        return False
    if not _matches_filter(configured=match_json.get("category"), actual=category):
        return False
    return True


def _global_notification_destinations() -> list[str]:
    # Preserve fallback behavior for tenants without explicit destination or route configuration.
    settings = get_settings()
    parsed: list[str] = []
    try:
        raw = json.loads(settings.notify_webhook_urls_json)
    except json.JSONDecodeError:
        raw = []
    if isinstance(raw, list):
        parsed.extend(str(value).strip() for value in raw if isinstance(value, str) and value.strip())
    adapter = settings.ops_notification_adapter.strip().lower()
    if adapter == "webhook" and settings.ops_notification_webhook_url:
        parsed.append(settings.ops_notification_webhook_url.strip())
    if not parsed and adapter == "noop":
        parsed.append("noop://default")
    deduped: list[str] = []
    seen: set[str] = set()
    for destination in parsed:
        if destination in seen:
            continue
        seen.add(destination)
        deduped.append(destination)
    return deduped


def _normalize_destinations_json(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            normalized.append({"destination_id": item.strip()})
            continue
        if isinstance(item, dict):
            destination_id = item.get("destination_id")
            if isinstance(destination_id, str) and destination_id.strip():
                normalized.append(
                    {
                        "destination_id": destination_id.strip(),
                        "enabled": bool(item.get("enabled", True)),
                    }
                )
    return normalized


async def resolve_destinations(
    *,
    session: AsyncSession,
    tenant_id: str,
    event_type: str,
    severity: str,
    source: str | None = None,
    category: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[ResolvedNotificationDestination]:
    # Resolve tenant destinations deterministically from routes, then tenant defaults, then global fallback.
    _ = metadata
    normalized_severity = severity.strip().lower()
    if normalized_severity not in _ALLOWED_SEVERITIES:
        normalized_severity = "low"
    normalized_event_type = event_type.strip().lower()
    normalized_source = source.strip().lower() if isinstance(source, str) and source.strip() else None
    normalized_category = category.strip().lower() if isinstance(category, str) and category.strip() else None

    destinations = (
        await session.execute(
            select(NotificationDestination)
            .where(
                NotificationDestination.tenant_id == tenant_id,
                NotificationDestination.enabled.is_(True),
            )
            .order_by(NotificationDestination.created_at.asc(), NotificationDestination.id.asc())
        )
    ).scalars().all()
    destination_map = {row.id: row for row in destinations}
    enabled_destination_ids = [row.id for row in destinations]

    routes = (
        await session.execute(
            select(NotificationRoute)
            .where(
                NotificationRoute.tenant_id == tenant_id,
                NotificationRoute.enabled.is_(True),
            )
            .order_by(NotificationRoute.priority.asc(), NotificationRoute.created_at.asc(), NotificationRoute.id.asc())
        )
    ).scalars().all()

    resolved: list[ResolvedNotificationDestination] = []
    seen_urls: set[str] = set()
    matched_route = False
    for route in routes:
        if not _matches_route(
            route=route,
            event_type=normalized_event_type,
            severity=normalized_severity,
            source=normalized_source,
            category=normalized_category,
        ):
            continue
        matched_route = True
        route_destinations = _normalize_destinations_json(route.destinations_json)
        for item in route_destinations:
            if item.get("enabled") is False:
                continue
            destination_id = str(item["destination_id"])
            destination = destination_map.get(destination_id)
            if destination is None:
                continue
            if destination.destination_url in seen_urls:
                continue
            seen_urls.add(destination.destination_url)
            resolved.append(
                ResolvedNotificationDestination(
                    destination_id=destination.id,
                    destination_url=destination.destination_url,
                    route_id=route.id,
                    source="route",
                )
            )
    if resolved:
        return resolved

    # If a route matched but produced no valid destination rows, degrade to tenant/global fallback instead of dropping events.
    _ = matched_route
    if enabled_destination_ids:
        for destination_id in enabled_destination_ids:
            row = destination_map[destination_id]
            resolved.append(
                ResolvedNotificationDestination(
                    destination_id=row.id,
                    destination_url=row.destination_url,
                    route_id=None,
                    source="tenant_destination",
                )
            )
        return resolved

    for destination_url in _global_notification_destinations():
        if destination_url in seen_urls:
            continue
        seen_urls.add(destination_url)
        resolved.append(
            ResolvedNotificationDestination(
                destination_id=None,
                destination_url=destination_url,
                route_id=None,
                source="global_default",
            )
        )
    return resolved
