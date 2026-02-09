from __future__ import annotations

from typing import Any

from nexusrag.apps.api.response import ErrorEnvelope


def _error_example(*, code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    # Build a consistent error envelope example for OpenAPI docs.
    payload: dict[str, Any] = {
        "error": {"code": code, "message": message},
        "meta": {"request_id": "req_example", "api_version": "v1"},
    }
    if details:
        payload["error"]["details"] = details
    return payload


DEFAULT_ERROR_RESPONSES: dict[int, dict[str, Any]] = {
    400: {
        "model": ErrorEnvelope,
        "description": "Bad request",
        "content": {
            "application/json": {
                "example": _error_example(code="BAD_REQUEST", message="Bad request"),
            }
        },
    },
    401: {
        "model": ErrorEnvelope,
        "description": "Unauthorized",
        "content": {
            "application/json": {
                "example": _error_example(code="AUTH_UNAUTHORIZED", message="Missing or invalid bearer token"),
            }
        },
    },
    402: {
        "model": ErrorEnvelope,
        "description": "Quota exceeded",
        "content": {
            "application/json": {
                "example": _error_example(
                    code="QUOTA_EXCEEDED",
                    message="Monthly request quota exceeded",
                    details={"period": "month", "limit": 10000, "used": 10000, "remaining": 0},
                ),
            }
        },
    },
    403: {
        "model": ErrorEnvelope,
        "description": "Forbidden",
        "content": {
            "application/json": {
                "example": _error_example(
                    code="AUTH_FORBIDDEN",
                    message="Insufficient role for this operation",
                ),
            }
        },
    },
    404: {
        "model": ErrorEnvelope,
        "description": "Not found",
        "content": {
            "application/json": {
                "example": _error_example(code="NOT_FOUND", message="Resource not found"),
            }
        },
    },
    409: {
        "model": ErrorEnvelope,
        "description": "Conflict",
        "content": {
            "application/json": {
                "example": _error_example(
                    code="IDEMPOTENCY_KEY_CONFLICT",
                    message="Idempotency-Key already used with different payload",
                ),
            }
        },
    },
    422: {
        "model": ErrorEnvelope,
        "description": "Validation error",
        "content": {
            "application/json": {
                "example": _error_example(
                    code="REQUEST_VALIDATION_ERROR",
                    message="Validation error",
                ),
            }
        },
    },
    429: {
        "model": ErrorEnvelope,
        "description": "Rate limited",
        "content": {
            "application/json": {
                "example": _error_example(
                    code="RATE_LIMITED",
                    message="Rate limit exceeded",
                    details={
                        "scope": "api_key",
                        "route_class": "read",
                        "retry_after_ms": 1200,
                    },
                ),
            }
        },
    },
    500: {
        "model": ErrorEnvelope,
        "description": "Internal server error",
        "content": {
            "application/json": {
                "example": _error_example(code="INTERNAL_ERROR", message="Internal server error"),
            }
        },
    },
    503: {
        "model": ErrorEnvelope,
        "description": "Service unavailable",
        "content": {
            "application/json": {
                "example": _error_example(code="SERVICE_UNAVAILABLE", message="Service unavailable"),
            }
        },
    },
}
