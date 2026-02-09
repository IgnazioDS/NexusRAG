from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from nexusrag.apps.api.response import error_response, is_versioned_request


_DEFAULT_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "AUTH_UNAUTHORIZED",
    402: "QUOTA_EXCEEDED",
    403: "AUTH_FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _default_code(status_code: int) -> str:
    # Map status codes to fallback error codes when none are provided.
    return _DEFAULT_ERROR_CODES.get(status_code, "UNKNOWN_ERROR")


def _split_detail(detail: Any, status_code: int) -> tuple[str, str, dict[str, Any] | None]:
    # Extract code/message/details from FastAPI HTTPException detail payloads.
    if isinstance(detail, dict):
        code = str(detail.get("code") or _default_code(status_code))
        message = str(detail.get("message") or "Request failed")
        details = {k: v for k, v in detail.items() if k not in {"code", "message"}}
        return code, message, details or None
    if isinstance(detail, str):
        return _default_code(status_code), detail, None
    return _default_code(status_code), "Request failed", None


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Normalize HTTPExceptions into the shared error envelope for v1 routes.
    if not is_versioned_request(request):
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    code, message, details = _split_detail(exc.detail, exc.status_code)
    payload = error_response(request=request, code=code, message=message, details=details)
    return JSONResponse(content=payload, status_code=exc.status_code, headers=exc.headers)


async def starlette_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    # Ensure Starlette-raised exceptions are also wrapped consistently for v1 routes.
    if not is_versioned_request(request):
        return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    code, message, details = _split_detail(exc.detail, exc.status_code)
    payload = error_response(request=request, code=code, message=message, details=details)
    return JSONResponse(content=payload, status_code=exc.status_code, headers=exc.headers)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Surface validation errors with structured details for UI/SDK parsing.
    if not is_versioned_request(request):
        return JSONResponse(content={"detail": exc.errors()}, status_code=422)
    payload = error_response(
        request=request,
        code="REQUEST_VALIDATION_ERROR",
        message="Validation error",
        details={"errors": exc.errors()},
    )
    return JSONResponse(content=payload, status_code=422)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Avoid leaking stack traces; return a stable internal error envelope.
    if not is_versioned_request(request):
        return JSONResponse(content={"detail": "Internal Server Error"}, status_code=500)
    payload = error_response(
        request=request,
        code="INTERNAL_ERROR",
        message="Internal server error",
    )
    return JSONResponse(content=payload, status_code=500)
