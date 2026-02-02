from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from nexusrag.domain.models import Chunk, Corpus
from nexusrag.core.config import EMBED_DIM
from nexusrag.ingestion.embeddings import embed_text
from nexusrag.persistence.db import SessionLocal


DEMO_TENANT_ID = "t1"
DEMO_CORPUS_ID = "c1"
DEMO_CORPUS_NAME = "Demo Corpus"


@dataclass(frozen=True)
class DemoSection:
    # Keep seed content deterministic and structured for repeatable embeddings.
    title: str
    text: str


@dataclass(frozen=True)
class DemoDocument:
    # Stable document metadata drives consistent citations and chunk indexes.
    document_uri: str
    title: str
    sections: tuple[DemoSection, ...]


def build_demo_documents() -> tuple[DemoDocument, ...]:
    # Keep the corpus small but varied to make retrieval behavior visible.
    return (
        DemoDocument(
            document_uri="demo://doc/1",
            title="Agent 2.0 Testing Strategy",
            sections=(
                DemoSection(
                    title="Overview",
                    text="Agent 2.0 emphasizes integration tests with deterministic fixtures.",
                ),
                DemoSection(
                    title="Unit Coverage",
                    text="Unit tests focus on embedding determinism and retrieval correctness.",
                ),
                DemoSection(
                    title="Release Gates",
                    text="Every release must pass a dockerized validation checklist.",
                ),
            ),
        ),
        DemoDocument(
            document_uri="demo://doc/2",
            title="NexusRAG Architecture Notes",
            sections=(
                DemoSection(
                    title="Streaming",
                    text="SSE streams token deltas as soon as the model yields output.",
                ),
                DemoSection(
                    title="State",
                    text="LangGraph captures history, retrievals, and checkpoints per session.",
                ),
                DemoSection(
                    title="Persistence",
                    text="Postgres stores sessions, messages, and retrieval chunks.",
                ),
            ),
        ),
        DemoDocument(
            document_uri="demo://doc/3",
            title="Operational Playbook",
            sections=(
                DemoSection(
                    title="Validation",
                    text="Developers should seed demo data before calling /run.",
                ),
                DemoSection(
                    title="Error Handling",
                    text="Missing Vertex credentials should emit a structured SSE error.",
                ),
                DemoSection(
                    title="Local Retrieval",
                    text="Pgvector cosine distance ranks chunks for local development.",
                ),
                DemoSection(
                    title="Observability",
                    text="Citations include source, score, and metadata for traceability.",
                ),
            ),
        ),
    )


def build_demo_chunks() -> list[Chunk]:
    # Build chunks deterministically to keep the seed idempotent and stable.
    chunks: list[Chunk] = []
    for document in build_demo_documents():
        for index, section in enumerate(document.sections):
            text = f"{section.title}: {section.text}"
            embedding = embed_text(text)
            if len(embedding) != EMBED_DIM:
                raise ValueError(f"Embedding dimension mismatch; expected {EMBED_DIM}.")
            chunks.append(
                Chunk(
                    id=uuid4(),
                    corpus_id=DEMO_CORPUS_ID,
                    document_uri=document.document_uri,
                    chunk_index=index,
                    text=text,
                    embedding=embedding,
                    metadata_json={
                        "title": document.title,
                        "section": section.title,
                        "source_type": "demo",
                    },
                )
            )
    return chunks


async def seed_demo() -> int:
    # Use the shared async session factory so env config matches the API container.
    async with SessionLocal() as session:
        corpus = await session.get(Corpus, DEMO_CORPUS_ID)
        if corpus is None:
            corpus = Corpus(
                id=DEMO_CORPUS_ID,
                tenant_id=DEMO_TENANT_ID,
                name=DEMO_CORPUS_NAME,
                # Configure local retrieval so the router works out of the box.
                provider_config_json={
                    "retrieval": {"provider": "local_pgvector", "top_k_default": 5}
                },
            )
            session.add(corpus)
        else:
            # Keep demo corpus metadata aligned without touching non-demo corpora.
            corpus.tenant_id = DEMO_TENANT_ID
            corpus.name = DEMO_CORPUS_NAME
            corpus.provider_config_json = {
                "retrieval": {"provider": "local_pgvector", "top_k_default": 5}
            }

        existing = await session.execute(
            select(Chunk.id).where(Chunk.corpus_id == DEMO_CORPUS_ID).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            await session.commit()
            print("Demo corpus already seeded; skipping.")
            return 0

        chunks = build_demo_chunks()
        session.add_all(chunks)
        await session.commit()
        print(f"Seeded demo corpus with {len(chunks)} chunks.")
        return 0


def main() -> int:
    # Surface clear failures and exit non-zero so CI/dev scripts can detect issues.
    try:
        return asyncio.run(seed_demo())
    except Exception as exc:  # noqa: BLE001 - surface any setup or DB errors
        print(f"seed_demo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
