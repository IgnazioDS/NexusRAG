from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from nexusrag.core.config import EMBED_DIM
from nexusrag.core.errors import RetrievalError
from nexusrag.domain.models import Chunk
from nexusrag.ingestion.embeddings import embed_text


class LocalPgVectorRetriever:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def retrieve(self, tenant_id: str, corpus_id: str, query: str, top_k: int) -> list[dict]:
        # tenant_id is unused for local retrieval but kept for a consistent interface.
        query_embedding = embed_text(query)
        if len(query_embedding) != EMBED_DIM:
            # Retrieval must fail fast if the embedding dimension doesn't match the schema.
            raise RetrievalError("query embedding dimension mismatch")

        # Clamp to a small, deterministic range to avoid unbounded queries in dev.
        top_k = max(1, min(int(top_k), 20))
        # Use cosine distance from pgvector; lower is more similar.
        distance_expr = Chunk.embedding.cosine_distance(query_embedding)

        stmt = (
            select(Chunk, distance_expr.label("distance"))
            .where(Chunk.corpus_id == corpus_id)
            # Secondary ordering keeps tie-breaking deterministic.
            .order_by(distance_expr.asc(), Chunk.id.asc())
            .limit(top_k)
        )

        try:
            result = await self._session.execute(stmt)
            rows = result.all()
        except SQLAlchemyError as exc:
            # Convert DB errors into a controlled retrieval error for SSE mapping.
            raise RetrievalError("pgvector query failed") from exc

        items: list[dict] = []
        for chunk, distance in rows:
            # Convert cosine distance to similarity and clamp to a sane [0, 1] range.
            score = 1.0 - float(distance)
            score = max(0.0, min(1.0, score))
            items.append(
                {
                    "text": chunk.text,
                    "score": score,
                    "source": chunk.document_uri,
                    "metadata": chunk.metadata_json or {},
                }
            )
        return items
