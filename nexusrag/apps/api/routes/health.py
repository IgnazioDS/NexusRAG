from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.services.prometheus_metrics import generate_metrics

router = APIRouter(tags=["health"], responses=DEFAULT_ERROR_RESPONSES)


class HealthResponse(BaseModel):
    status: str


# Allow legacy unwrapped responses while v1 middleware wraps them into envelopes.
@router.get("/health", response_model=SuccessEnvelope[HealthResponse] | HealthResponse)
async def health(request: Request) -> dict:
    # Keep health responses wrapped for consistent client parsing.
    payload = HealthResponse(status="ok")
    return success_response(request=request, data=payload)


@router.get(
    "/metrics",
    include_in_schema=False,
    summary="Prometheus metrics scrape endpoint",
)
async def metrics() -> Response:
    # Expose the in-process telemetry as a Prometheus text-format scrape target.
    # Wire a Prometheus scrape job to /v1/metrics (no auth required for ops tooling).
    data, content_type = generate_metrics()
    return Response(content=data, media_type=content_type)
