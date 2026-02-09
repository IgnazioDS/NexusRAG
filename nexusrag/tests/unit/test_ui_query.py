from __future__ import annotations

import pytest
from sqlalchemy import literal_column

from nexusrag.services.ui_query import (
    CursorError,
    SortField,
    SortSpec,
    build_cursor_payload,
    decode_cursor,
    encode_cursor,
    sort_token,
)


def test_cursor_roundtrip() -> None:
    payload = build_cursor_payload(
        scope="ui.documents",
        tenant_id="t1",
        sort_fields=[
            SortField("created_at", SortSpec(column=literal_column("created_at")), "desc")
        ],
        row_values={"created_at": "2026-02-09T00:00:00Z"},
        row_id="doc-1",
    )
    token = encode_cursor(payload, "secret")
    decoded = decode_cursor(token, "secret")
    assert decoded["scope"] == "ui.documents"
    assert decoded["tenant_id"] == "t1"
    assert decoded["id"] == "doc-1"


def test_cursor_invalid_signature() -> None:
    payload = {"scope": "ui.documents", "tenant_id": "t1", "sort": "", "values": {}, "id": "x"}
    token = encode_cursor(payload, "secret")
    with pytest.raises(CursorError):
        decode_cursor(token, "other")


def test_sort_token_normalization() -> None:
    fields = [
        SortField("created_at", SortSpec(column=literal_column("created_at")), "desc"),
        SortField("name", SortSpec(column=literal_column("name")), "asc"),
    ]
    assert sort_token(fields) == "-created_at,name"
