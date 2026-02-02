from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import get_db, get_tenant_id
from nexusrag.core.errors import RetrievalConfigError
from nexusrag.persistence.repos import corpora as corpora_repo
from nexusrag.providers.retrieval.config import normalize_provider_config


router = APIRouter(prefix="/corpora", tags=["corpora"])


class CorpusResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    provider_config_json: dict[str, Any]
    created_at: str


class CorpusPatchRequest(BaseModel):
    name: str | None = Field(default=None)
    provider_config_json: dict[str, Any] | None = Field(default=None)


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


@router.get("")
async def list_corpora(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[CorpusResponse]:
    try:
        corpora = await corpora_repo.list_corpora_by_tenant(db, tenant_id)
    except SQLAlchemyError as exc:
        # Shield clients from raw database errors while still returning a useful status.
        raise HTTPException(status_code=500, detail="Database error while listing corpora") from exc
    return [_to_response(corpus) for corpus in corpora]


@router.get("/{corpus_id}")
async def get_corpus(
    corpus_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CorpusResponse:
    try:
        corpus = await corpora_repo.get_by_tenant_and_id(db, tenant_id, corpus_id)
    except SQLAlchemyError as exc:
        # Return a generic 500 to avoid leaking database details.
        raise HTTPException(status_code=500, detail="Database error while fetching corpus") from exc
    if corpus is None:
        # Use 404 to avoid leaking cross-tenant corpus existence.
        raise HTTPException(status_code=404, detail="Corpus not found")
    return _to_response(corpus)


@router.patch("/{corpus_id}")
async def patch_corpus(
    corpus_id: str,
    payload: CorpusPatchRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CorpusResponse:
    provider_config_json = None
    if payload.provider_config_json is not None:
        try:
            # Validate and normalize once to keep router and API behavior consistent.
            provider_config_json = normalize_provider_config(payload.provider_config_json)
        except RetrievalConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
    return _to_response(corpus)
