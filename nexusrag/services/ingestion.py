from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import EMBED_DIM
from nexusrag.domain.models import Chunk, Document
from nexusrag.ingestion.chunking import chunk_text
from nexusrag.ingestion.embeddings import embed_text
from nexusrag.persistence.db import SessionLocal
from nexusrag.persistence.repos import documents as documents_repo


async def _load_document(session: AsyncSession, document_id: str) -> Document | None:
    result = await session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def ingest_document(document_id: str, text: str) -> None:
    # Run ingestion in a background task with its own DB session.
    async with SessionLocal() as session:
        doc = await _load_document(session, document_id)
        if doc is None:
            return

        try:
            await documents_repo.update_status(session, document_id, status="processing")
            await session.commit()

            # Ensure idempotency for reingestion by clearing existing chunks.
            await session.execute(delete(Chunk).where(Chunk.document_id == document_id))

            chunks: list[Chunk] = []
            for index, (chunk_text_value, start, end) in enumerate(chunk_text(text)):
                embedding = embed_text(chunk_text_value)
                if len(embedding) != EMBED_DIM:
                    raise ValueError(f"Embedding dimension mismatch; expected {EMBED_DIM}.")
                chunks.append(
                    Chunk(
                        id=uuid4(),
                        corpus_id=doc.corpus_id,
                        document_id=document_id,
                        document_uri=f"document://{document_id}",
                        chunk_index=index,
                        text=chunk_text_value,
                        embedding=embedding,
                        metadata_json={
                            "filename": doc.filename,
                            "content_type": doc.content_type,
                            "offset_start": start,
                            "offset_end": end,
                        },
                    )
                )

            session.add_all(chunks)
            await session.commit()

            await documents_repo.update_status(session, document_id, status="succeeded")
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - store an error message for operators
            await session.rollback()
            await documents_repo.update_status(
                session,
                document_id,
                status="failed",
                error_message=str(exc),
            )
            await session.commit()
