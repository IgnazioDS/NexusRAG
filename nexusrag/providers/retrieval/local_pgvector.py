from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.domain.models import Chunk
from nexusrag.ingestion.embeddings import embed_text


class LocalPgVectorRetriever:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def retrieve(self, corpus_id: str, query: str, top_k: int) -> list[dict]:
        query_embedding = embed_text(query)
        distance_expr = Chunk.embedding.cosine_distance(query_embedding)

        stmt = (
            select(Chunk, distance_expr.label("distance"))
            .where(Chunk.corpus_id == corpus_id)
            .order_by(distance_expr.asc())
            .limit(top_k)
        )

        result = await self._session.execute(stmt)
        rows = result.all()

        items: list[dict] = []
        for chunk, distance in rows:
            score = 1.0 - float(distance)
            items.append(
                {
                    "text": chunk.text,
                    "score": score,
                    "source": chunk.document_uri,
                    "metadata": chunk.metadata_json or {},
                }
            )
        return items
