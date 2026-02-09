from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.apps.api.response import SuccessEnvelope, success_response

router = APIRouter(tags=["health"], responses=DEFAULT_ERROR_RESPONSES)


class HealthResponse(BaseModel):
    status: str


# Allow legacy unwrapped responses while v1 middleware wraps them into envelopes.
@router.get("/health", response_model=SuccessEnvelope[HealthResponse] | HealthResponse)
async def health(request: Request) -> dict:
    # Keep health responses wrapped for consistent client parsing.
    payload = HealthResponse(status="ok")
    return success_response(request=request, data=payload)
