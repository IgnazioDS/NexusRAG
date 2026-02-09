from __future__ import annotations

from starlette.requests import Request

from nexusrag.apps.api import rate_limit


def _make_request(path: str, method: str) -> Request:
    # Construct a minimal ASGI scope for route-class mapping tests.
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1234),
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


def test_token_bucket_math_refills_and_caps() -> None:
    now_ms = 1_000
    tokens = rate_limit._calculate_tokens(
        tokens=0.0,
        last_ms=0,
        now_ms=now_ms,
        rate=2.0,
        burst=5,
    )
    assert tokens == 2.0

    capped = rate_limit._calculate_tokens(
        tokens=4.5,
        last_ms=0,
        now_ms=10_000,
        rate=2.0,
        burst=5,
    )
    assert capped == 5.0


def test_retry_after_computation() -> None:
    retry_ms = rate_limit._retry_after_ms(0.0, rate=2.0, cost=1)
    assert retry_ms == 500

    retry_zero = rate_limit._retry_after_ms(2.0, rate=2.0, cost=1)
    assert retry_zero == 0


def test_route_class_mapping() -> None:
    run_request = _make_request("/run", "POST")
    assert rate_limit.route_class_for_request(run_request) == (rate_limit.ROUTE_CLASS_RUN, 3)

    docs_get = _make_request("/documents", "GET")
    assert rate_limit.route_class_for_request(docs_get) == (rate_limit.ROUTE_CLASS_READ, 1)

    docs_post = _make_request("/documents", "POST")
    assert rate_limit.route_class_for_request(docs_post) == (rate_limit.ROUTE_CLASS_MUTATION, 1)

    corpora_patch = _make_request("/corpora/c1", "PATCH")
    assert rate_limit.route_class_for_request(corpora_patch) == (rate_limit.ROUTE_CLASS_MUTATION, 1)

    ops_health = _make_request("/ops/health", "GET")
    assert rate_limit.route_class_for_request(ops_health) == (rate_limit.ROUTE_CLASS_OPS, 1)

    audit_events = _make_request("/audit/events", "GET")
    assert rate_limit.route_class_for_request(audit_events) == (rate_limit.ROUTE_CLASS_OPS, 1)

    admin_patch = _make_request("/admin/quotas/t1", "PATCH")
    assert rate_limit.route_class_for_request(admin_patch) == (rate_limit.ROUTE_CLASS_MUTATION, 1)

    self_serve_create = _make_request("/self-serve/api-keys", "POST")
    assert rate_limit.route_class_for_request(self_serve_create) == (rate_limit.ROUTE_CLASS_MUTATION, 1)
