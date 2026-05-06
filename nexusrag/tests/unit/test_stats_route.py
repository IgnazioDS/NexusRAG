"""Unit test for the public /api/stats Tier-A route.

Covers the must-hold guarantees from
https://github.com/IgnazioDS/IgnazioDS/blob/main/TELEMETRY_SCHEMA.md:

- HTTP 200 in all branches (never 5xx)
- All required Tier-A fields present
- schema_version == 1
- Response is parseable JSON
- Status flips to "degraded" when the aggregator raises, but the contract
  envelope stays valid and metrics zero out (no internal error leaks)
- CORS + cache headers are set
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from nexusrag.apps.api.main import create_app
from nexusrag.persistence.repos.query_log import QueryAggregates

_REQUIRED_TOP_FIELDS = {
    "system",
    "mode",
    "status",
    "uptime_pct_30d",
    "last_deployed_at",
    "last_active_at",
    "metrics",
    "schema_version",
    "generated_at",
}
_REQUIRED_METRIC_FIELDS = {
    "queries_total",
    "queries_24h",
    "queries_7d",
    "p50_latency_ms",
    "p95_latency_ms",
    "avg_retrieval_size",
    "indexed_chunks",
}


def _aggregates_with_data() -> QueryAggregates:
    return QueryAggregates(
        queries_total=1234,
        queries_24h=42,
        queries_7d=300,
        p50_latency_ms=480,
        p95_latency_ms=910,
        avg_retrieval_size=6,
        indexed_chunks=12_034,
        last_active_at=datetime(2026, 4, 27, 18, 0, tzinfo=timezone.utc),
    )


def _client_with_mocked_db():
    app = create_app()
    # Override get_db so the route can run without a real Postgres connection.
    from nexusrag.apps.api import deps as deps_module

    async def _fake_db():
        yield AsyncMock()

    app.dependency_overrides[deps_module.get_db] = _fake_db
    return TestClient(app)


def test_happy_path_matches_tier_a_contract() -> None:
    client = _client_with_mocked_db()
    with patch(
        "nexusrag.apps.api.routes.stats.aggregate",
        new=AsyncMock(return_value=_aggregates_with_data()),
    ):
        response = client.get("/api/stats")

    assert response.status_code == 200
    payload = response.json()
    assert _REQUIRED_TOP_FIELDS.issubset(payload.keys())
    assert _REQUIRED_METRIC_FIELDS.issubset(payload["metrics"].keys())
    assert payload["schema_version"] == 1
    assert payload["mode"] == "live"
    assert payload["status"] == "operational"
    assert payload["system"] == "nexusrag"
    assert payload["metrics"]["queries_total"] == 1234
    assert payload["metrics"]["queries_24h"] == 42
    assert payload["last_active_at"] == "2026-04-27T18:00:00Z"


def test_degraded_when_aggregator_fails() -> None:
    client = _client_with_mocked_db()
    with patch(
        "nexusrag.apps.api.routes.stats.aggregate",
        new=AsyncMock(side_effect=RuntimeError("postgres unreachable")),
    ):
        response = client.get("/api/stats")

    # Contract: HTTP 200 even when the underlying DB is unreachable.
    assert response.status_code == 200
    payload = response.json()
    # Envelope still valid.
    assert _REQUIRED_TOP_FIELDS.issubset(payload.keys())
    assert payload["schema_version"] == 1
    assert payload["status"] == "degraded"
    # Metrics zeroed; no internal error string leaked.
    body_text = response.text
    assert "postgres unreachable" not in body_text
    assert payload["metrics"]["queries_total"] == 0
    assert payload["metrics"]["queries_24h"] == 0
    assert payload["last_active_at"] is None


def test_response_headers_match_contract() -> None:
    client = _client_with_mocked_db()
    with patch(
        "nexusrag.apps.api.routes.stats.aggregate",
        new=AsyncMock(return_value=_aggregates_with_data()),
    ):
        response = client.get("/api/stats")

    assert response.headers["cache-control"].startswith("public, max-age=30")
    assert response.headers["access-control-allow-origin"] == "*"
    assert "GET" in response.headers["access-control-allow-methods"]
    assert response.headers["content-type"].startswith("application/json")


def test_options_preflight_returns_204_with_cors_headers() -> None:
    client = _client_with_mocked_db()
    response = client.options("/api/stats")
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"
    assert "GET" in response.headers["access-control-allow-methods"]


@pytest.mark.parametrize(
    "field,expected_type",
    [
        ("system", str),
        ("mode", str),
        ("status", str),
        ("uptime_pct_30d", float),
        ("metrics", dict),
        ("schema_version", int),
        ("generated_at", str),
    ],
)
def test_field_types(field: str, expected_type: type) -> None:
    client = _client_with_mocked_db()
    with patch(
        "nexusrag.apps.api.routes.stats.aggregate",
        new=AsyncMock(return_value=_aggregates_with_data()),
    ):
        response = client.get("/api/stats")
    payload = response.json()
    assert isinstance(payload[field], expected_type), (
        f"{field} expected {expected_type.__name__}, got {type(payload[field]).__name__}"
    )
