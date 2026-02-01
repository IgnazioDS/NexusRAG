# NexusRAG (vertical slice)

NexusRAG is a multi-cloud, stateful, streaming RAG agent platform. This repo bootstraps a working vertical slice with:
- FastAPI + SSE `/run`
- Postgres + pgvector retrieval
- LangGraph state machine
- Gemini via Vertex AI (streaming)

## Prerequisites
- Docker + Docker Compose
- Python 3.11+ (optional for local dev)

## Quickstart
1) Copy env file:
```
cp .env.example .env
```
2) Start services:
```
docker compose up --build
```
3) Run migrations:
```
docker compose exec api alembic upgrade head
```

## Seed a corpus + chunks (local pgvector)
You can seed with a tiny script inside the container:
```
docker compose exec api python - <<'PY'
import asyncio
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Corpus, Chunk
from nexusrag.ingestion.embeddings import embed_text

settings = get_settings()
engine = create_async_engine(settings.database_url)
Session = async_sessionmaker(engine, expire_on_commit=False)

async def main():
    async with Session() as session:
        corpus_id = "c1"
        existing = await session.get(Corpus, corpus_id)
        if not existing:
            session.add(Corpus(id=corpus_id, tenant_id="t1", name="Demo", provider_config_json={}))
        text = "Agent 2.0 testing strategy focuses on integration coverage and deterministic mocks."
        chunk = Chunk(
            id=uuid4(),
            corpus_id=corpus_id,
            document_uri="doc://demo",
            chunk_index=0,
            text=text,
            embedding=embed_text(text),
            metadata_json={"title": "Demo Doc"},
        )
        session.add(chunk)
        await session.commit()

asyncio.run(main())
PY
```

## Call `/run` (SSE)
```
curl -N -H "Content-Type: application/json" \
  -X POST http://localhost:8000/run \
  -d '{
    "session_id":"s1",
    "tenant_id":"t1",
    "corpus_id":"c1",
    "message":"What is the testing strategy of agent 2.0?",
    "top_k":5,
    "audio":false
  }'
```

## Notes
- If Vertex credentials/config are missing, `/run` emits an SSE `error` event with a clear message.
- Retrieval uses a deterministic fake embedding (no external embedding APIs).

## Validation Checklist
1) Copy env file:
```
cp .env.example .env
```
2) Start services:
```
docker compose up --build -d
```
3) Run migrations:
```
docker compose exec api alembic upgrade head
```
4) Health check:
```
curl -s http://localhost:8000/health
```
5) Seed demo data:
```
skip until PHASE 2 (seed script will live at scripts/seed_demo.py)
```
6) SSE run (expect `token.delta` then `message.final`, or `error` if Vertex config missing):
```
curl -N -H "Content-Type: application/json" \
  -X POST http://localhost:8000/run \
  -d '{
    "session_id":"s1",
    "tenant_id":"t1",
    "corpus_id":"c1",
    "message":"What is the testing strategy of agent 2.0?",
    "top_k":5,
    "audio":false
  }'
```
7) Run tests in container:
```
docker compose exec api pytest -q
```

## Tests
```
pytest
```

## Release process
- Branch naming: `feat/<short-scope>` or `fix/<short-scope>`
- Bump version: update `pyproject.toml` and add a new entry in `CHANGELOG.md`
- Tag release: `git tag vX.Y.Z`
- Use the repo's default branch name (e.g., `main`); do not assume a specific remote.
