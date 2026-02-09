from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import and_, or_
from sqlalchemy.sql import ColumnElement


class CursorError(ValueError):
    # Raise for malformed or tampered cursor tokens.
    pass


@dataclass(frozen=True)
class SortSpec:
    # Define sortable fields and optional serialization/parsing rules.
    column: ColumnElement[Any]
    parser: Callable[[Any], Any] | None = None
    serializer: Callable[[Any], Any] | None = None


@dataclass(frozen=True)
class SortField:
    # Capture the parsed sort direction for a single field.
    name: str
    spec: SortSpec
    direction: str


def sort_token(sort_fields: list[SortField]) -> str:
    # Emit a stable sort token for cursor validation.
    parts = []
    for field in sort_fields:
        prefix = "-" if field.direction == "desc" else ""
        parts.append(f"{prefix}{field.name}")
    return ",".join(parts)


def parse_sort(
    *,
    sort: str | None,
    allowed: dict[str, SortSpec],
    default: list[SortField],
) -> list[SortField]:
    # Parse comma-delimited sort strings into validated field specs.
    if not sort:
        return default
    fields: list[SortField] = []
    seen = set()
    for raw in sort.split(","):
        raw = raw.strip()
        if not raw:
            continue
        direction = "desc" if raw.startswith("-") else "asc"
        name = raw[1:] if raw.startswith("-") else raw
        if name in seen:
            continue
        spec = allowed.get(name)
        if spec is None:
            raise CursorError(f"Unsupported sort field: {name}")
        fields.append(SortField(name=name, spec=spec, direction=direction))
        seen.add(name)
    if not fields:
        return default
    return fields


def _serialize_value(value: Any, serializer: Callable[[Any], Any] | None) -> Any:
    # Convert values to JSON-friendly formats for cursor payloads.
    if serializer:
        return serializer(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def _parse_value(value: Any, parser: Callable[[Any], Any] | None) -> Any:
    # Convert serialized cursor values back into comparable types.
    if parser:
        return parser(value)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return value


def build_cursor_payload(
    *,
    scope: str,
    tenant_id: str,
    sort_fields: list[SortField],
    row_values: dict[str, Any],
    row_id: Any,
) -> dict[str, Any]:
    # Persist the last row values to build an opaque cursor token.
    values: dict[str, Any] = {}
    for field in sort_fields:
        values[field.name] = _serialize_value(row_values[field.name], field.spec.serializer)
    return {
        "v": 1,
        "scope": scope,
        "tenant_id": tenant_id,
        "sort": sort_token(sort_fields),
        "values": values,
        "id": row_id,
    }


def encode_cursor(payload: dict[str, Any], secret: str) -> str:
    # Sign cursor payloads to prevent client-side tampering.
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    encoded = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    return f"{encoded}.{signature}"


def decode_cursor(token: str, secret: str) -> dict[str, Any]:
    # Verify cursor signatures and return the decoded payload.
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise CursorError("Invalid cursor format") from exc
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
    except (ValueError, binascii.Error) as exc:  # type: ignore[name-defined]
        raise CursorError("Invalid cursor encoding") from exc
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise CursorError("Invalid cursor signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise CursorError("Invalid cursor payload") from exc
    if not isinstance(payload, dict):
        raise CursorError("Invalid cursor payload")
    return payload


def validate_cursor_payload(
    *,
    payload: dict[str, Any],
    expected_scope: str,
    expected_tenant_id: str,
    expected_sort: str,
) -> dict[str, Any]:
    # Ensure cursor metadata matches the current request context.
    if payload.get("scope") != expected_scope:
        raise CursorError("Cursor scope mismatch")
    if payload.get("tenant_id") != expected_tenant_id:
        raise CursorError("Cursor tenant mismatch")
    if payload.get("sort") != expected_sort:
        raise CursorError("Cursor sort mismatch")
    values = payload.get("values")
    if not isinstance(values, dict):
        raise CursorError("Cursor values missing")
    if "id" not in payload:
        raise CursorError("Cursor id missing")
    return payload


def build_cursor_filter(
    *,
    sort_fields: list[SortField],
    cursor_values: dict[str, Any],
    row_id: Any,
    id_column: ColumnElement[Any],
) -> ColumnElement[bool]:
    # Build lexicographic pagination filters for keyset-based paging.
    if not sort_fields:
        raise CursorError("Sort fields are required for cursor paging")

    parsed_values = {
        field.name: _parse_value(cursor_values.get(field.name), field.spec.parser)
        for field in sort_fields
    }
    id_direction = sort_fields[0].direction
    id_value = row_id

    def _compare(column: ColumnElement[Any], direction: str, value: Any) -> ColumnElement[bool]:
        return column > value if direction == "asc" else column < value

    conditions: list[ColumnElement[bool]] = []
    for idx, field in enumerate(sort_fields):
        prefix = [
            sort_fields[p].spec.column == parsed_values[sort_fields[p].name] for p in range(idx)
        ]
        conditions.append(
            and_(
                *prefix,
                _compare(field.spec.column, field.direction, parsed_values[field.name]),
            )
        )

    prefix_all = [field.spec.column == parsed_values[field.name] for field in sort_fields]
    conditions.append(and_(*prefix_all, _compare(id_column, id_direction, id_value)))

    return or_(*conditions)
