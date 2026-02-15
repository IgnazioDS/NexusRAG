from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any
from uuid import uuid4

from nexusrag.domain.models import ScimGroup, ScimGroupMembership, ScimIdentity, TenantUser
from nexusrag.services.auth.api_keys import ROLE_ORDER, normalize_role


SCIM_SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_SCHEMA_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCIM_SCHEMA_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_SCHEMA_PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"

TOKEN_PREFIX = "nrgscim_"


@dataclass
class ScimUserInput:
    external_id: str | None
    user_name: str | None
    email: str | None
    display_name: str | None
    active: bool | None
    groups: list[str] | None


def _utc_now() -> datetime:
    # Normalize SCIM timestamps to UTC for consistent exports.
    return datetime.now(timezone.utc)


def hash_scim_token(raw_token: str) -> str:
    # Store SCIM bearer tokens as irreversible hashes.
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_scim_token() -> tuple[str, str, str, str]:
    # Create a SCIM token with a traceable prefix for admin operations.
    token_id = uuid4().hex
    secret = secrets.token_urlsafe(32)
    raw_token = f"{TOKEN_PREFIX}{token_id}_{secret}"
    token_prefix = raw_token[:12]
    return token_id, raw_token, token_prefix, hash_scim_token(raw_token)


def _select_highest_role(roles: list[str]) -> str | None:
    # Choose the highest role by RBAC precedence.
    normalized: list[str] = []
    for role in roles:
        if not role:
            continue
        try:
            normalized.append(normalize_role(role))
        except ValueError:
            continue
    if not normalized:
        return None
    return max(normalized, key=lambda role: ROLE_ORDER.get(role, 0))


def resolve_role_from_groups(groups: list[ScimGroup]) -> str | None:
    # Resolve role binding from SCIM groups with explicit role assignments.
    roles = [group.role_binding for group in groups if group.role_binding]
    return _select_highest_role([role for role in roles if role])


def parse_scim_user_payload(payload: dict[str, Any]) -> ScimUserInput:
    # Parse SCIM user payload into normalized fields.
    user_name = payload.get("userName")
    external_id = payload.get("externalId")
    display_name = payload.get("displayName")
    active = payload.get("active")
    email = _extract_email(payload.get("emails"))
    groups = _extract_group_ids(payload.get("groups"))
    return ScimUserInput(
        external_id=str(external_id) if external_id is not None else None,
        user_name=str(user_name) if user_name is not None else None,
        email=email,
        display_name=str(display_name) if display_name is not None else None,
        active=bool(active) if active is not None else None,
        groups=groups,
    )


def apply_scim_user_patch(
    *,
    payload: dict[str, Any],
    current: ScimUserInput,
) -> ScimUserInput:
    # Apply SCIM PATCH operations to a normalized user payload.
    operations = payload.get("Operations") or []
    updated = ScimUserInput(**current.__dict__)
    for operation in operations:
        op = str(operation.get("op", "replace")).lower()
        path = str(operation.get("path") or "").lower()
        value = operation.get("value")
        if op not in {"replace", "add", "remove"}:
            continue
        if path in {"username", "userName".lower()}:
            if op != "remove":
                updated.user_name = str(value) if value is not None else updated.user_name
        elif path == "displayname":
            if op != "remove":
                updated.display_name = str(value) if value is not None else updated.display_name
        elif path == "active":
            if op != "remove":
                updated.active = bool(value)
        elif path == "externalid":
            if op != "remove":
                updated.external_id = str(value) if value is not None else updated.external_id
        elif path.startswith("emails"):
            if op != "remove":
                updated.email = _extract_email(value)
        elif path.startswith("groups"):
            if op == "remove":
                updated.groups = []
            else:
                updated.groups = _extract_group_ids(value)
    return updated


def parse_scim_group_payload(payload: dict[str, Any]) -> tuple[str | None, str | None, list[str] | None]:
    # Parse SCIM group payload into normalized fields.
    display_name = payload.get("displayName")
    external_id = payload.get("externalId")
    members = _extract_member_ids(payload.get("members"))
    return (
        str(display_name) if display_name is not None else None,
        str(external_id) if external_id is not None else None,
        members,
    )


def apply_scim_group_patch(
    *,
    payload: dict[str, Any],
    current_members: list[str],
    current_name: str,
) -> tuple[str, list[str]]:
    # Apply SCIM group PATCH operations to membership lists.
    operations = payload.get("Operations") or []
    members = list(current_members)
    name = current_name
    for operation in operations:
        op = str(operation.get("op", "replace")).lower()
        path = str(operation.get("path") or "").lower()
        value = operation.get("value")
        if op not in {"replace", "add", "remove"}:
            continue
        if path == "displayname":
            if op != "remove":
                name = str(value)
            continue
        if path in {"members", "members.value"}:
            value_members = _extract_member_ids(value)
            if value_members is None:
                continue
            if op == "replace":
                members = value_members
            elif op == "add":
                for member in value_members:
                    if member not in members:
                        members.append(member)
            elif op == "remove":
                members = [member for member in members if member not in value_members]
    return name, members


def build_scim_user_resource(
    *,
    user: TenantUser,
    identity: ScimIdentity | None,
    groups: list[ScimGroup],
) -> dict[str, Any]:
    # Format a SCIM user response using the core schema.
    created_at = user.created_at.isoformat() if user.created_at else _utc_now().isoformat()
    updated_at = user.updated_at.isoformat() if user.updated_at else created_at
    emails = []
    if user.email:
        emails.append({"value": user.email, "primary": True})
    group_entries = [
        {"value": group.id, "display": group.display_name} for group in groups
    ]
    payload: dict[str, Any] = {
        "schemas": [SCIM_SCHEMA_USER],
        "id": user.id,
        "userName": user.external_subject,
        "externalId": identity.external_id if identity else None,
        "displayName": user.display_name,
        "active": user.status == "active",
        "emails": emails,
        "groups": group_entries,
        "meta": {
            "resourceType": "User",
            "created": created_at,
            "lastModified": updated_at,
        },
    }
    return {k: v for k, v in payload.items() if v is not None}


def build_scim_group_resource(
    *,
    group: ScimGroup,
    members: list[TenantUser],
) -> dict[str, Any]:
    # Format a SCIM group response using the core schema.
    created_at = group.created_at.isoformat() if group.created_at else _utc_now().isoformat()
    updated_at = group.updated_at.isoformat() if group.updated_at else created_at
    member_entries = [{"value": member.id, "display": member.display_name or member.email} for member in members]
    payload: dict[str, Any] = {
        "schemas": [SCIM_SCHEMA_GROUP],
        "id": group.id,
        "displayName": group.display_name,
        "externalId": group.external_id,
        "members": member_entries,
        "meta": {
            "resourceType": "Group",
            "created": created_at,
            "lastModified": updated_at,
        },
    }
    return {k: v for k, v in payload.items() if v is not None}


def build_scim_list_response(
    *,
    resources: list[dict[str, Any]],
    total_results: int,
    start_index: int,
    items_per_page: int,
) -> dict[str, Any]:
    # Build a standard SCIM ListResponse payload.
    return {
        "schemas": [SCIM_SCHEMA_LIST],
        "totalResults": total_results,
        "startIndex": start_index,
        "itemsPerPage": items_per_page,
        "Resources": resources,
    }


def build_scim_service_provider_config() -> dict[str, Any]:
    # Return a minimal ServiceProviderConfig response for SCIM clients.
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": True},
        "etag": {"supported": False},
    }


def apply_active_status(active: bool | None) -> str | None:
    # Convert SCIM active flag into tenant user status.
    if active is None:
        return None
    return "active" if active else "disabled"


def compute_token_expiry(days: int | None) -> datetime | None:
    # Compute expiry timestamp from configured TTL days.
    if days is None:
        return None
    return _utc_now() + timedelta(days=days)


def _extract_email(raw_emails: Any) -> str | None:
    # Choose primary or first email entry from SCIM payloads.
    if not raw_emails:
        return None
    if isinstance(raw_emails, dict):
        return str(raw_emails.get("value")) if raw_emails.get("value") else None
    if isinstance(raw_emails, list):
        primary = next((item for item in raw_emails if item.get("primary")), None)
        candidate = primary or raw_emails[0]
        return str(candidate.get("value")) if candidate.get("value") else None
    return None


def _extract_group_ids(raw_groups: Any) -> list[str] | None:
    # Extract group identifiers from SCIM group arrays.
    if raw_groups is None:
        return None
    if isinstance(raw_groups, list):
        ids = []
        for item in raw_groups:
            if isinstance(item, dict) and item.get("value"):
                ids.append(str(item.get("value")))
            elif isinstance(item, str):
                ids.append(item)
        return ids
    return None


def _extract_member_ids(raw_members: Any) -> list[str] | None:
    # Extract member ids from SCIM group membership arrays.
    if raw_members is None:
        return None
    if isinstance(raw_members, list):
        ids = []
        for item in raw_members:
            if isinstance(item, dict) and item.get("value"):
                ids.append(str(item.get("value")))
            elif isinstance(item, str):
                ids.append(item)
        return ids
    return None
