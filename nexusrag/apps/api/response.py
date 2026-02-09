from __future__ import annotations

from typing import Any, Generic, TypeVar
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, Field


API_VERSION = "v1"

T = TypeVar("T")


class ResponseMeta(BaseModel):
    # Include request/version metadata for consistent client tracing.
    request_id: str
    api_version: str = Field(default=API_VERSION)


class ErrorDetail(BaseModel):
    # Standardize error codes/messages with optional structured details.
    code: str
    message: str
    details: dict[str, Any] | None = None


class SuccessEnvelope(BaseModel, Generic[T]):
    # Wrap successful responses in a consistent envelope.
    data: T
    meta: ResponseMeta


class ErrorEnvelope(BaseModel):
    # Wrap error responses in a consistent envelope.
    error: ErrorDetail
    meta: ResponseMeta


def get_request_id(request: Request) -> str:
    # Use existing request IDs when provided to preserve traceability.
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return request_id
    header_request_id = request.headers.get("X-Request-Id")
    if header_request_id:
        request.state.request_id = header_request_id
        return header_request_id
    generated = str(uuid4())
    request.state.request_id = generated
    return generated


def is_versioned_request(request: Request) -> bool:
    # Detect v1 routes to apply the standardized response envelope.
    return request.url.path.startswith(f"/{API_VERSION}")


def success_response(*, request: Request, data: Any) -> dict[str, Any]:
    # Return the standard success envelope for versioned routes only.
    if not is_versioned_request(request):
        return data
    meta = ResponseMeta(request_id=get_request_id(request))
    return {"data": data, "meta": meta.model_dump()}


def error_response(
    *,
    request: Request,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Return the standard error envelope with request metadata.
    meta = ResponseMeta(request_id=get_request_id(request))
    error = ErrorDetail(code=code, message=message, details=details)
    return {"error": error.model_dump(exclude_none=True), "meta": meta.model_dump()}
