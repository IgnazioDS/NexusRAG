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
Run the demo seed script inside the container:
```
docker compose exec api python scripts/seed_demo.py
```

## What it seeds
- corpus_id: `c1`
- tenant_id: `t1`
- chunks: 10 demo chunks across 3 documents
- idempotency: if chunks for `c1` already exist, the script no-ops and prints “already seeded”

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
docker compose exec api python scripts/seed_demo.py
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

## Retrieval sanity check
This query should match seeded content about testing strategy and release gates:
```
curl -N -H "Content-Type: application/json" \
  -X POST http://localhost:8000/run \
  -d '{
    "session_id":"s1",
    "tenant_id":"t1",
    "corpus_id":"c1",
    "message":"What are the release gates for Agent 2.0?",
    "top_k":5,
    "audio":false
  }'
```
Expected behavior:
- If Vertex is configured, you will see `token.delta` events followed by `message.final`.
- If Vertex is missing, you will see an `error` event, but retrieval and persistence still run before the LLM call.

## Tests
```
pytest
```

## Makefile shortcuts
```
make up
make migrate
make seed
make test
```

## Release process
- Branch naming: `feat/<short-scope>` or `fix/<short-scope>`
- Bump version: update `pyproject.toml` and add a new entry in `CHANGELOG.md`
- Tag release: `git tag vX.Y.Z`
- Use the repo's default branch name (e.g., `main`); do not assume a specific remote.
