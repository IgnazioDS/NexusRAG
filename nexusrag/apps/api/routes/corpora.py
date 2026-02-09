from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import (
    Principal,
    get_db,
    idempotency_key_header,
    reject_tenant_id_in_body,
    require_role,
)
from nexusrag.apps.api.openapi import DEFAULT_ERROR_RESPONSES
from nexusrag.core.errors import RetrievalConfigError
from nexusrag.persistence.repos import corpora as corpora_repo
from nexusrag.providers.retrieval.config import normalize_provider_config
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.apps.api.response import SuccessEnvelope, success_response
from nexusrag.services.entitlements import (
    FEATURE_CORPORA_PATCH_PROVIDER,
    require_feature,
    require_retrieval_provider,
)
from nexusrag.services.idempotency import (
    build_replay_response,
    check_idempotency,
    compute_request_hash,
    store_idempotency_response,
)


router = APIRouter(prefix="/corpora", tags=["corpora"], responses=DEFAULT_ERROR_RESPONSES)


class CorpusResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    provider_config_json: dict[str, Any]
    created_at: str


class CorpusPatchRequest(BaseModel):
    name: str | None = Field(default=None)
    provider_config_json: dict[str, Any] | None = Field(default=None)

    # Reject unknown fields so tenant_id cannot be supplied in the payload.
    model_config = {"extra": "forbid"}


def _to_response(corpus) -> CorpusResponse:
    # Serialize datetimes for JSON output while keeping response fields explicit.
    created_at: datetime = corpus.created_at
    return CorpusResponse(
        id=corpus.id,
        tenant_id=corpus.tenant_id,
        name=corpus.name,
        provider_config_json=corpus.provider_config_json,
        created_at=created_at.isoformat(),
    )


# Allow legacy unwrapped responses; v1 middleware wraps envelopes.
@router.get("", response_model=SuccessEnvelope[list[CorpusResponse]] | list[CorpusResponse])
async def list_corpora(
    principal: Principal = Depends(require_role("reader")),
    db: AsyncSession = Depends(get_db),
) -> list[CorpusResponse]:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    tenant_id = principal.tenant_id
    try:
        corpora = await corpora_repo.list_corpora_by_tenant(db, tenant_id)
    except SQLAlchemyError as exc:
        # Shield clients from raw database errors while still returning a useful status.
        raise HTTPException(status_code=500, detail="Database error while listing corpora") from exc
    return [_to_response(corpus) for corpus in corpora]


@router.get("/{corpus_id}", response_model=SuccessEnvelope[CorpusResponse] | CorpusResponse)
async def get_corpus(
    corpus_id: str,
    principal: Principal = Depends(require_role("reader")),
    db: AsyncSession = Depends(get_db),
) -> CorpusResponse:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    tenant_id = principal.tenant_id
    try:
        corpus = await corpora_repo.get_by_tenant_and_id(db, tenant_id, corpus_id)
    except SQLAlchemyError as exc:
        # Return a generic 500 to avoid leaking database details.
        raise HTTPException(status_code=500, detail="Database error while fetching corpus") from exc
    if corpus is None:
        # Use 404 to avoid leaking cross-tenant corpus existence.
        raise HTTPException(status_code=404, detail="Corpus not found")
    return _to_response(corpus)


@router.patch("/{corpus_id}", response_model=SuccessEnvelope[CorpusResponse] | CorpusResponse)
async def patch_corpus(
    corpus_id: str,
    request: Request,
    payload: CorpusPatchRequest,
    _reject_tenant: None = Depends(reject_tenant_id_in_body),
    _idempotency_key: str | None = Depends(idempotency_key_header),
    principal: Principal = Depends(require_role("editor")),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[CorpusResponse] | CorpusResponse:
    # Bind tenant scope from the authenticated principal to prevent spoofing.
    tenant_id = principal.tenant_id
    request_hash = compute_request_hash(payload.model_dump())
    idempotency_ctx, replay = await check_idempotency(
        request=request,
        db=db,
        tenant_id=tenant_id,
        actor_id=principal.api_key_id,
        request_hash=request_hash,
    )
    if replay is not None:
        return build_replay_response(replay)
    provider_config_json = None
    if payload.provider_config_json is not None:
        try:
            # Validate and normalize once to keep router and API behavior consistent.
            provider_config_json = normalize_provider_config(payload.provider_config_json)
        except RetrievalConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Enforce plan entitlements before allowing provider config mutations.
        await require_feature(
            session=db,
            tenant_id=principal.tenant_id,
            feature_key=FEATURE_CORPORA_PATCH_PROVIDER,
        )
        provider_name = provider_config_json.get("retrieval", {}).get("provider")
        if provider_name:
            await require_retrieval_provider(
                session=db,
                tenant_id=principal.tenant_id,
                provider_name=provider_name,
            )

    updated_fields: list[str] = []
    if payload.name is not None:
        updated_fields.append("name")
    if payload.provider_config_json is not None:
        updated_fields.append("provider_config_json")

    try:
        corpus = await corpora_repo.update_fields(
            db,
            tenant_id,
            corpus_id,
            name=payload.name,
            provider_config_json=provider_config_json,
        )
        if corpus is None:
            raise HTTPException(status_code=404, detail="Corpus not found")
        await db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        # Surface a generic error and keep the transaction clean for the caller.
        raise HTTPException(status_code=500, detail="Database error while updating corpus") from exc

    request_ctx = get_request_context(request)
    # Record the corpus mutation after the update succeeds.
    await record_event(
        session=db,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="corpora.updated",
        outcome="success",
        resource_type="corpus",
        resource_id=corpus_id,
        request_id=request_ctx["request_id"],
        ip_address=request_ctx["ip_address"],
        user_agent=request_ctx["user_agent"],
        metadata={"updated_fields": updated_fields},
        commit=True,
        best_effort=True,
    )
    response_payload = _to_response(corpus)
    payload_body = success_response(request=request, data=response_payload)
    await store_idempotency_response(
        db=db,
        context=idempotency_ctx,
        response_status=200,
        response_body=jsonable_encoder(payload_body),
    )
    return payload_body
