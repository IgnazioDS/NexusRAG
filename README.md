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

## Retrieval routing (per corpus)
Each corpus specifies its retrieval provider in `corpora.provider_config_json`:

Local pgvector:
```
{
  "retrieval": {
    "provider": "local_pgvector",
    "top_k_default": 5
  }
}
```

AWS Bedrock Knowledge Bases:
```
{
  "retrieval": {
    "provider": "aws_bedrock_kb",
    "knowledge_base_id": "KB123",
    "region": "us-east-1",
    "top_k_default": 5
  }
}
```

Vertex AI Search (Discovery Engine):
```
{
  "retrieval": {
    "provider": "gcp_vertex",
    "project": "my-gcp-project",
    "location": "us-central1",
    "resource_id": "your-datastore-id",
    "top_k_default": 5
  }
}
```

Switching a corpus:
1) Update `corpora.provider_config_json` for the target corpus.
2) `{}` is accepted and normalized to `local_pgvector` with a default `top_k_default` of 5.
3) Ensure cloud credentials exist at runtime (AWS/Vertex), but tests do not require live creds.

## Authentication & RBAC
All protected endpoints require API keys via:
```
Authorization: Bearer <api_key>
```

Create a key (example):
```
docker compose exec api python scripts/create_api_key.py --tenant t1 --role admin --name local-admin
```
Export the key for curl examples:
```
export API_KEY=<api_key_from_script>
export ADMIN_API_KEY=$API_KEY
```
Revoke a key:
```
docker compose exec api python scripts/revoke_api_key.py <key_id>
```

Role matrix:
| Endpoint | reader | editor | admin |
| --- | --- | --- | --- |
| `/run` | ✅ | ✅ | ✅ |
| `GET /documents` | ✅ | ✅ | ✅ |
| `POST/DELETE /documents`, `/documents/*/reindex` | ❌ | ✅ | ✅ |
| `GET /corpora` | ✅ | ✅ | ✅ |
| `PATCH /corpora` | ❌ | ✅ | ✅ |
| `/ops/*` | ❌ | ❌ | ✅ |

Dev-only bypass:
- Set `AUTH_DEV_BYPASS=true` to allow `X-Tenant-Id` + optional `X-Role` (defaults to `admin`).
- This is intended for local development only; keep it disabled in production.

## Corpora API
List corpora:
```
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/corpora
```

Get a corpus:
```
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/corpora/c1
```

Patch provider_config_json:
```
curl -s -X PATCH -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/corpora/c1 \
  -d '{
    "provider_config_json": {
      "retrieval": {
        "provider": "aws_bedrock_kb",
        "knowledge_base_id": "KB123",
        "region": "us-east-1",
        "top_k_default": 5
      }
    }
  }'
```

## Optional TTS audio output
Enable TTS with environment variables:
- `TTS_PROVIDER` = `openai` | `fake` | `none` (default `none`)
- `OPENAI_API_KEY` (required for OpenAI)
- `OPENAI_TTS_MODEL` (default `gpt-4o-mini-tts`)
- `OPENAI_TTS_VOICE` (default `alloy`)
- `AUDIO_BASE_URL` (default `http://localhost:8000`)

Audio files are stored locally under `var/audio/` (dev-only).

Example `/run` with audio enabled:
```
curl -N -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  -X POST http://localhost:8000/run \
  -d '{
    "session_id":"s-audio-1",
    "corpus_id":"c1",
    "message":"Summarize the demo corpus.",
    "top_k":5,
    "audio":true
  }'
```

SSE events:
- `audio.ready` → `{"type":"audio.ready","request_id":"...","data":{"audio_url":"http://localhost:8000/audio/<id>.mp3","audio_id":"<id>","mime":"audio/mpeg"}}`
- `audio.error` → `{"type":"audio.error","request_id":"...","data":{"code":"TTS_ERROR","message":"..."}}`

## Ingestion (documents → chunks)
Supported types: `text/plain`, `text/markdown` (JSON with `{"text": "..."}` is accepted as a file upload).
Ingestion is async: the API enqueues a Redis-backed job and returns `202 Accepted`.
Lifecycle: `queued` → `processing` → `succeeded|failed` (see `failure_reason` on failures).
Raw text ingestion is deterministic and idempotent when a `document_id` is supplied.

Upload a document (returns `202` with `job_id` + `status_url`):
```
curl -s -X POST -H "Authorization: Bearer $API_KEY" \
  -F "corpus_id=c1" \
  -F "file=@./example.txt;type=text/plain" \
  http://localhost:8000/documents
```

Ingest raw text (returns `202` with `job_id` + `status_url`):
```
Set `overwrite: true` to requeue a failed or succeeded document with the same `document_id`.
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/documents/text \
  -d '{
    "corpus_id": "c1",
    "text": "Some raw text to ingest.",
    "document_id": "doc-123",
    "filename": "notes.txt",
    "overwrite": false
  }'
```

Check status / poll:
```
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/documents/<document_id>
```

List documents:
```
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/documents
```

Reindex a document (returns `202` with `job_id` + `status_url`):
```
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/documents/<document_id>/reindex \
  -d '{
    "chunk_size_chars": 1200,
    "chunk_overlap_chars": 150
  }'
```

Delete a document:
```
curl -s -X DELETE -H "Authorization: Bearer $API_KEY" http://localhost:8000/documents/<document_id>
```

Troubleshooting:
- If status stays `queued`, ensure the ingestion worker is running and Redis is reachable.
- If status stays `processing`, check for queue backlog or long-running ingestions.
- If status is `failed`, inspect `failure_reason` and worker logs, then reindex or re-upload.
- Delete returns `409` for in-flight documents (`queued`/`processing`).

## Ops Endpoints
Ops endpoints return `200` even when dependencies are degraded, surfacing the degraded field instead of failing.
Ops endpoints require an admin API key.

Health summary:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" http://localhost:8000/ops/health
```

Ingestion stats (last 24 hours by default):
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" "http://localhost:8000/ops/ingestion?hours=24"
```

Metrics snapshot (JSON):
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" http://localhost:8000/ops/metrics
```

Heartbeat interpretation:
- `worker_heartbeat_age_s` shows seconds since the last worker heartbeat.
- If the heartbeat is missing or stale, `/ops/health` reports `status: degraded`.

Queue depth:
- `queue_depth` reports pending jobs in the Redis ingestion queue.
- If Redis is unavailable, `queue_depth` is `null` and `/ops/health` reports `redis: degraded`.

## Cloud retrieval real-run (credentials required)
Use the smoke script to validate retrieval routing without calling the LLM:
```
docker compose exec api python scripts/provider_smoke.py \
  --tenant t1 --corpus c1 --query "test query" --top-k 5
```

### AWS Bedrock Knowledge Bases
Required environment (examples):
- `AWS_REGION` (or `AWS_DEFAULT_REGION`)
- `AWS_PROFILE` (or `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + optional `AWS_SESSION_TOKEN`)

Permissions (high level):
- `bedrock:Retrieve` on the target knowledge base

Smoke validation:
```
docker compose exec api python scripts/provider_smoke.py \
  --tenant t1 --corpus c1 --query "bedrock test" --top-k 5
```

### Vertex AI Search (Discovery Engine)
Required environment (examples):
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION` (or `VERTEX_LOCATION`)
- Application Default Credentials (ADC), e.g. `gcloud auth application-default login`

Smoke validation:
```
docker compose exec api python scripts/provider_smoke.py \
  --tenant t1 --corpus c1 --query "vertex test" --top-k 5
```

### Troubleshooting error codes
- `AWS_CONFIG_MISSING`: required AWS env vars or KB config missing
- `AWS_AUTH_ERROR`: missing/invalid AWS credentials
- `AWS_RETRIEVAL_ERROR`: Bedrock retrieval failed (check permissions or KB id)
- `VERTEX_RETRIEVAL_CONFIG_MISSING`: missing Vertex config in corpus or env
- `VERTEX_RETRIEVAL_AUTH_ERROR`: missing/invalid Google ADC credentials
- `VERTEX_RETRIEVAL_ERROR`: Vertex retrieval failed (check resource id)

## Call `/run` (SSE)
```
curl -N -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  -X POST http://localhost:8000/run \
  -d '{
    "session_id":"s1",
    "corpus_id":"c1",
    "message":"What is the testing strategy of agent 2.0?",
    "top_k":5,
    "audio":false
  }'
```

## Notes
- If Vertex credentials/config are missing, `/run` emits an SSE `error` event with a clear message.
- Retrieval uses a deterministic fake embedding (no external embedding APIs).
- Set `DEBUG_EVENTS=true` to emit `debug.retrieval` SSE events after retrieval for validation.

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
4) Create an API key:
```
docker compose exec api python scripts/create_api_key.py --tenant t1 --role admin --name local-admin
```
5) Export the key:
```
export API_KEY=<api_key_from_script>
```
6) Health check:
```
curl -s http://localhost:8000/health
```
7) Seed demo data:
```
docker compose exec api python scripts/seed_demo.py
```
8) SSE run (expect `token.delta` then `message.final`, or `error` if Vertex config missing):
```
curl -N -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  -X POST http://localhost:8000/run \
  -d '{
    "session_id":"s1",
    "corpus_id":"c1",
    "message":"What is the testing strategy of agent 2.0?",
    "top_k":5,
    "audio":false
  }'
```
9) Run tests in container:
```
docker compose exec api pytest -q
```

## Retrieval sanity check
This query should match seeded content about testing strategy and release gates:
```
curl -N -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -X POST http://localhost:8000/run \
  -d '{
    "session_id":"s1",
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
