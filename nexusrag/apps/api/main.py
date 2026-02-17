from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import StreamingResponse

from nexusrag.apps.api.routes.audio import router as audio_router
from nexusrag.apps.api.routes.admin import router as admin_router
from nexusrag.apps.api.routes.audit import router as audit_router
from nexusrag.apps.api.routes.authz_admin import router as authz_admin_router
from nexusrag.apps.api.routes.corpora import router as corpora_router
from nexusrag.apps.api.routes.documents import router as documents_router
from nexusrag.apps.api.routes.compliance_admin import router as compliance_admin_router
from nexusrag.apps.api.routes.compliance_ops import router as compliance_ops_router
from nexusrag.apps.api.routes.costs_admin import router as costs_admin_router
from nexusrag.apps.api.routes.costs_self_serve import router as costs_self_serve_router
from nexusrag.apps.api.routes.crypto_admin import router as crypto_admin_router
from nexusrag.apps.api.routes.governance_admin import router as governance_admin_router
from nexusrag.apps.api.routes.governance_ops import router as governance_ops_router
from nexusrag.apps.api.routes.health import router as health_router
from nexusrag.apps.api.routes.identity_admin import router as identity_admin_router
from nexusrag.apps.api.routes.ops import router as ops_router
from nexusrag.apps.api.routes.run import router as run_router
from nexusrag.apps.api.routes.scim import router as scim_router
from nexusrag.apps.api.routes.self_serve import router as self_serve_router
from nexusrag.apps.api.routes.sla_admin import router as sla_admin_router
from nexusrag.apps.api.routes.sso import router as sso_router
from nexusrag.apps.api.routes.ui import router as ui_router
from nexusrag.core.logging import configure_logging
from nexusrag.apps.api.errors import (
    http_exception_handler,
    starlette_http_exception_handler,
    validation_exception_handler,
    unhandled_exception_handler,
    tenant_predicate_exception_handler,
)
from nexusrag.apps.api.response import API_VERSION, is_versioned_request
from nexusrag.apps.api.rate_limit import route_class_for_request
from nexusrag.services.telemetry import record_request
from nexusrag.persistence.guards import TenantPredicateError


_LEGACY_SUNSET_DAYS = 90
_LEGACY_EXEMPT_PREFIXES = (
    "/v1",
    "/docs",
    "/openapi.json",
    "/redoc",
)
_ENVELOPE_EXEMPT_PREFIXES = (
    "/v1/openapi.json",
    "/v1/docs",
    "/v1/redoc",
)


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="NexusRAG API")

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):  # type: ignore[override]
        # Preserve incoming request IDs or assign a new one for traceability.
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        request.state.request_id = request_id
        start = time.monotonic()
        response = await call_next(request)
        latency_ms = (time.monotonic() - start) * 1000.0
        route_class, _cost = route_class_for_request(request)
        record_request(
            path=request.url.path,
            route_class=route_class,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        # Wrap versioned JSON responses in the standardized success envelope.
        if (
            is_versioned_request(request)
            and not request.url.path.startswith(_ENVELOPE_EXEMPT_PREFIXES)
            and response.status_code < 400
            and response.media_type == "application/json"
            and not isinstance(response, StreamingResponse)
        ):
            raw_body = getattr(response, "body", None)
            if raw_body:
                try:
                    payload = json.loads(raw_body)
                except (TypeError, ValueError):
                    payload = None
                if payload is not None:
                    is_enveloped = (
                        isinstance(payload, dict)
                        and "data" in payload
                        and "meta" in payload
                        and isinstance(payload.get("meta"), dict)
                        and payload["meta"].get("api_version") == API_VERSION
                    )
                    if not is_enveloped:
                        wrapped = {
                            "data": payload,
                            "meta": {"request_id": request_id, "api_version": API_VERSION},
                        }
                        wrapped_response = JSONResponse(
                            content=wrapped,
                            status_code=response.status_code,
                        )
                        for key, value in response.headers.items():
                            if key.lower() in {"content-length", "content-type"}:
                                continue
                            wrapped_response.headers[key] = value
                        response = wrapped_response

        response.headers.setdefault("X-Request-Id", request_id)
        # Mark legacy routes with deprecation headers to guide clients to /v1.
        if not request.url.path.startswith(_LEGACY_EXEMPT_PREFIXES):
            sunset_at = datetime.now(timezone.utc) + timedelta(days=_LEGACY_SUNSET_DAYS)
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = format_datetime(sunset_at)
            response.headers["Link"] = '</v1/docs>; rel=\"successor-version\"'
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        return await starlette_http_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        return await unhandled_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError):
        return await validation_exception_handler(request, exc)

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        return await http_exception_handler(request, exc)

    @app.exception_handler(TenantPredicateError)
    async def _tenant_predicate_exception_handler(request: Request, exc: TenantPredicateError):
        return await tenant_predicate_exception_handler(request, exc)

    # Mount versioned v1 API routes.
    app.include_router(audio_router, prefix=f"/{API_VERSION}")
    # Expose admin endpoints for tenant quota management.
    app.include_router(admin_router, prefix=f"/{API_VERSION}")
    app.include_router(crypto_admin_router, prefix=f"/{API_VERSION}")
    app.include_router(compliance_admin_router, prefix=f"/{API_VERSION}")
    app.include_router(compliance_ops_router, prefix=f"/{API_VERSION}")
    app.include_router(costs_admin_router, prefix=f"/{API_VERSION}")
    app.include_router(costs_self_serve_router, prefix=f"/{API_VERSION}")
    app.include_router(governance_admin_router, prefix=f"/{API_VERSION}")
    app.include_router(identity_admin_router, prefix=f"/{API_VERSION}")
    # Expose ABAC policy and document ACL management for admins.
    app.include_router(authz_admin_router, prefix=f"/{API_VERSION}")
    # Expose admin-only audit endpoints for security investigations.
    app.include_router(audit_router, prefix=f"/{API_VERSION}")
    app.include_router(documents_router, prefix=f"/{API_VERSION}")
    app.include_router(health_router, prefix=f"/{API_VERSION}")
    # Expose ops endpoints for ingestion observability and health checks.
    app.include_router(ops_router, prefix=f"/{API_VERSION}")
    app.include_router(governance_ops_router, prefix=f"/{API_VERSION}")
    # Expose tenant self-serve endpoints for admin lifecycle operations.
    app.include_router(self_serve_router, prefix=f"/{API_VERSION}")
    # Expose SSO discovery and callback routes for enterprise identity.
    app.include_router(sso_router, prefix=f"/{API_VERSION}")
    app.include_router(scim_router, prefix=f"/{API_VERSION}")
    app.include_router(sla_admin_router, prefix=f"/{API_VERSION}")
    # Expose UI-focused BFF endpoints for frontend integration.
    app.include_router(ui_router, prefix=f"/{API_VERSION}")
    app.include_router(corpora_router, prefix=f"/{API_VERSION}")
    app.include_router(run_router, prefix=f"/{API_VERSION}")

    # Retain unversioned legacy routes as deprecated compatibility aliases.
    app.include_router(audio_router, include_in_schema=False)
    app.include_router(admin_router, include_in_schema=False)
    app.include_router(crypto_admin_router, include_in_schema=False)
    app.include_router(compliance_admin_router, include_in_schema=False)
    app.include_router(compliance_ops_router, include_in_schema=False)
    app.include_router(costs_admin_router, include_in_schema=False)
    app.include_router(costs_self_serve_router, include_in_schema=False)
    app.include_router(governance_admin_router, include_in_schema=False)
    app.include_router(identity_admin_router, include_in_schema=False)
    # Retain authz admin routes for legacy compatibility aliases.
    app.include_router(authz_admin_router, include_in_schema=False)
    app.include_router(audit_router, include_in_schema=False)
    app.include_router(documents_router, include_in_schema=False)
    app.include_router(health_router, include_in_schema=False)
    app.include_router(ops_router, include_in_schema=False)
    app.include_router(governance_ops_router, include_in_schema=False)
    app.include_router(self_serve_router, include_in_schema=False)
    app.include_router(sso_router, include_in_schema=False)
    app.include_router(scim_router, include_in_schema=False)
    app.include_router(sla_admin_router, include_in_schema=False)
    app.include_router(corpora_router, include_in_schema=False)
    app.include_router(run_router, include_in_schema=False)

    # Serve versioned OpenAPI JSON and docs endpoints for v1 consumers.
    @app.get("/v1/openapi.json", include_in_schema=False)
    async def openapi_json() -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/v1/docs", include_in_schema=False)
    async def v1_docs() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/v1/openapi.json", title="NexusRAG API v1")

    @app.get("/docs", include_in_schema=False)
    async def docs_redirect() -> RedirectResponse:
        return RedirectResponse(url="/v1/docs")

    def custom_openapi() -> dict:
        # Inject bearer auth and version metadata into the OpenAPI schema.
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title="NexusRAG API",
            version=API_VERSION,
            routes=app.routes,
        )
        schema["servers"] = [{"url": "http://localhost:8000"}]
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["BearerAuth"] = {"type": "http", "scheme": "bearer"}
        public_paths = {"/v1/health", "/v1/audio/{audio_id}.mp3"}
        for path, operations in schema.get("paths", {}).items():
            if path in public_paths:
                continue
            for operation in operations.values():
                operation.setdefault("security", [{"BearerAuth": []}])
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi

    return app


app = create_app()
