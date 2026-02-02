from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import Corpus


async def get_corpus(session: AsyncSession, corpus_id: str) -> Corpus | None:
    result = await session.execute(select(Corpus).where(Corpus.id == corpus_id))
    return result.scalar_one_or_none()


async def get_corpus_for_tenant(session: AsyncSession, corpus_id: str, tenant_id: str) -> Corpus | None:
    # Ensure tenant scoping to prevent cross-tenant corpus access.
    result = await session.execute(
        select(Corpus).where(Corpus.id == corpus_id, Corpus.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def list_corpora_by_tenant(session: AsyncSession, tenant_id: str) -> list[Corpus]:
    # Stable ordering avoids non-deterministic API responses for the same tenant.
    result = await session.execute(
        select(Corpus)
        .where(Corpus.tenant_id == tenant_id)
        .order_by(Corpus.created_at, Corpus.id)
    )
    return list(result.scalars().all())


async def get_by_tenant_and_id(session: AsyncSession, tenant_id: str, corpus_id: str) -> Corpus | None:
    # Alias to keep tenant scoping explicit at call sites.
    return await get_corpus_for_tenant(session, corpus_id, tenant_id)


async def update_fields(
    session: AsyncSession,
    tenant_id: str,
    corpus_id: str,
    *,
    name: str | None = None,
    provider_config_json: dict | None = None,
) -> Corpus | None:
    # Fetch first to enforce tenant scoping and avoid accidental upserts.
    corpus = await get_corpus_for_tenant(session, corpus_id, tenant_id)
    if corpus is None:
        return None

    if name is not None:
        corpus.name = name
    if provider_config_json is not None:
        corpus.provider_config_json = provider_config_json
    return corpus
