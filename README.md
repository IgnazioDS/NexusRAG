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

1) Start services:

```
docker compose up --build
```

1) Run migrations:

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
| `/v1/run` | ✅ | ✅ | ✅ |
| `GET /v1/documents` | ✅ | ✅ | ✅ |
| `POST/DELETE /v1/documents`, `/v1/documents/*/reindex` | ❌ | ✅ | ✅ |
| `GET /v1/corpora` | ✅ | ✅ | ✅ |
| `PATCH /v1/corpora` | ❌ | ✅ | ✅ |
| `/v1/ops/*` | ❌ | ❌ | ✅ |

Dev-only bypass:

- Set `AUTH_DEV_BYPASS=true` to allow `X-Tenant-Id` + optional `X-Role` (defaults to `admin`).
- This is intended for local development only; keep it disabled in production.

## Authorization Model (RBAC + ABAC + Document ACL)

The platform layers ABAC on top of existing RBAC and document ACLs. Decision order for document actions:

1. Tenant boundary (non-bypassable).
2. Kill switches / maintenance gates.
3. RBAC role gate.
4. Document ACL evaluation (explicit grants; expired grants ignored).
5. ABAC policy evaluation (deny first, then allow; priority-aware).
6. Default deny (configurable via `AUTHZ_DEFAULT_DENY`).

Notes:

- Document creators receive an `owner` ACL entry on create.
- Admin role does not bypass document ACLs unless `AUTHZ_ADMIN_BYPASS_DOCUMENT_ACL=true`.
- Wildcard policies on both `resource_type` and `action` require `AUTHZ_ALLOW_WILDCARDS=true`.

Policy DSL example (deny high sensitivity docs):

```json
{
  "name": "deny-high-sensitivity",
  "effect": "deny",
  "resource_type": "document",
  "action": "read",
  "priority": 200,
  "condition_json": {
    "eq": [{ "var": "resource.labels.sensitivity" }, "high"]
  }
}
```

Policy DSL example (allow editors during business hours):

```json
{
  "name": "allow-editors-hours",
  "effect": "allow",
  "resource_type": "document",
  "action": "write",
  "priority": 100,
  "condition_json": {
    "all": [
      { "eq": [{ "var": "principal.role" }, "editor"] },
      { "time_between": [{ "var": "request.time" }, { "start": "09:00", "end": "18:00" }] }
    ]
  }
}
```

Simulate a policy before enabling it:

```bash
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \\
  -H "Content-Type: application/json" \\
  http://localhost:8000/v1/admin/authz/policies/<policy_id>/simulate \\
  -d '{
    "resource_type": "document",
    "action": "read",
    "principal": { "role": "reader" },
    "resource": { "labels": { "sensitivity": "high" } }
  }'
```

Grant a document permission:

```bash
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \\
  -H "Content-Type: application/json" \\
  http://localhost:8000/v1/admin/authz/documents/<document_id>/permissions \\
  -d '{"principal_type": "user", "principal_id": "<user_id>", "permission": "read"}'
```

## API Versioning & Compatibility

Stable API routes are versioned under `/v1` (recommended for all new clients).

Legacy unversioned routes remain as deprecated aliases and will sunset on:

- **Sun, 10 May 2026 00:00:00 +0000**

Legacy responses include:

- `Deprecation: true`
- `Sunset: <RFC 1123 date>`
- `Link: </v1/docs>; rel="successor-version"`

Migration guidance:

- Prefix all routes with `/v1`.
- Update clients to parse `data`/`meta` and `error`/`meta` envelopes.
- Use `Idempotency-Key` for write endpoints.

### Success envelope (JSON endpoints)

```
{
  "data": ...,
  "meta": {
    "request_id": "...",
    "api_version": "v1"
  }
}
```

### Error envelope (all errors)

```
{
  "error": {
    "code": "STRING_CODE",
    "message": "Human readable",
    "details": { ... }
  },
  "meta": {
    "request_id": "...",
    "api_version": "v1"
  }
}
```

Notes:

- SSE streams (`/v1/run` streaming) keep the existing event payloads and are not wrapped.
- Legacy routes keep pre-v1 response shapes (no envelope).

### Idempotency

Write endpoints accept `Idempotency-Key` (max 128 chars). Behavior:

- First request stores the response for 24h.
- Same key + same payload returns the stored response.
- Same key + different payload returns `409 IDEMPOTENCY_KEY_CONFLICT`.

## Audit Logs

Audit events are stored in the `audit_events` table and exposed via admin-only endpoints for investigations.

Event taxonomy:

| Category | event_type | Description |
| --- | --- | --- |
| Auth/security | `auth.api_key.created` | API key created via script |
| Auth/security | `auth.api_key.revoked` | API key revoked via script |
| Auth/security | `auth.access.success` | API key authenticated successfully |
| Auth/security | `auth.access.failure` | API key authentication failed |
| Auth/security | `rbac.forbidden` | Authenticated principal lacked required role |
| Data operations | `documents.ingest.enqueued` | Document ingestion enqueued |
| Data operations | `documents.reindex.enqueued` | Document reindex enqueued |
| Data operations | `documents.deleted` | Document deleted |
| Data operations | `corpora.updated` | Corpus fields updated |
| Data operations | `run.invoked` | `/run` invocation accepted |
| Data operations | `ops.viewed` | Ops endpoints accessed |
| Security | `security.rate_limited` | Request throttled by rate limiting |
| System | `system.rate_limit.degraded` | Rate limiting degraded due to Redis error |
| Quota | `quota.soft_cap_reached` | Soft cap threshold reached for a tenant period |
| Quota | `quota.hard_cap_blocked` | Request blocked due to hard cap enforcement |
| Quota | `quota.overage_observed` | Overage observed when hard cap is disabled |
| Billing | `billing.usage_recorded` | Sampled usage snapshot for metering |
| Billing | `billing.webhook.failure` | Billing webhook delivery failed |
| Self-serve | `selfserve.api_key.created` | Tenant admin created an API key |
| Self-serve | `selfserve.api_key.revoked` | Tenant admin revoked an API key |
| Self-serve | `selfserve.api_key.listed` | Tenant admin listed API keys |
| Self-serve | `selfserve.usage.viewed` | Tenant admin viewed usage dashboards |
| Self-serve | `selfserve.plan.viewed` | Tenant admin viewed plan details |
| Self-serve | `selfserve.billing_webhook_tested` | Tenant admin tested billing webhook delivery |
| Plans | `plan.upgrade_requested` | Tenant requested a plan upgrade |
| System | `system.worker.heartbeat.missed` | Optional: worker heartbeat missing |
| System | `system.error` | Optional: handled internal error |

Redaction policy:

- Never store plaintext API keys, Authorization headers, full user message content, or raw document text.
- Keys matching `api_key`, `authorization`, `token`, `secret`, `password`, `text`, or `content` are stored as `[REDACTED]`.
- Store only identifiers, counts, and high-level metadata.

List events:

```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/audit/events?limit=50"
```

Filter events:

```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/audit/events?event_type=rbac.forbidden&outcome=failure&limit=20"
```

## Frontend Integration (BFF)

UI-focused endpoints live under `/v1/ui/*` and return normalized shapes for web apps:

- `GET /v1/ui/bootstrap`
- `GET /v1/ui/dashboard/summary`
- `GET /v1/ui/documents`
- `GET /v1/ui/activity`
- `POST /v1/ui/actions/reindex-document`

Query conventions:

- `q` full-text filter
- `sort` comma list (e.g., `-created_at,name`)
- `limit` 1..100 (default 25)
- `cursor` opaque token (preferred)
- filters: `status`, `corpus_id`, `created_from`, `created_to`, `actor_type`, `event_type`

Pagination response shape:

```
{
  "data": {
    "items": [...],
    "page": { "next_cursor": "...", "has_more": true },
    "facets": { "status": [{"value":"succeeded","count":12}] }
  },
  "meta": { "request_id": "...", "api_version": "v1" }
}
```

Invalid cursors return `400` with `INVALID_CURSOR`.

Optimistic action response shape:

```
{
  "data": {
    "action_id": "...",
    "status": "accepted",
    "accepted_at": "...",
    "optimistic": { "entity": "document", "id": "...", "patch": { "status": "queued" } },
    "poll_url": "/v1/documents/<id>"
  },
  "meta": { "request_id": "...", "api_version": "v1" }
}
```

SSE protocol for `/v1/run`:

- Order: `request.accepted` → `token.delta*` → `message.final` → `audio.ready|audio.error` → `done`
- Every event payload includes `seq`
- Heartbeat:

```
event: heartbeat
data: {"ts":"...","request_id":"...","seq":7}
```

- Reconnects send `Last-Event-ID`; server responds with `resume.unsupported` (restart required).

## Rate Limiting

Rate limits use a Redis-backed token bucket with sustained rate + burst capacity. Limits are enforced per API key and per tenant; requests are allowed only when both buckets have capacity.
Clients should respect `Retry-After` and `X-RateLimit-Retry-After-Ms` headers and apply exponential backoff on `429`/`503` responses (SDKs include retry helpers).

Route classes:

| Class | Scope | Paths |
| --- | --- | --- |
| run | strict | `POST /run` |
| mutation | write | `POST/PATCH/DELETE /documents`, `PATCH /corpora`, `/admin/quotas/*`, audit write endpoints (if added) |
| read | read | `GET` endpoints (except ops/audit events) |
| ops | ops | `/ops/*` and `/audit/events*` |

Default thresholds:

| Route class | Key RPS | Key burst | Tenant RPS | Tenant burst |
| --- | --- | --- | --- | --- |
| run | 1 | 5 | 3 | 15 |
| mutation | 2 | 10 | 5 | 25 |
| read | 5 | 20 | 15 | 60 |
| ops | 2 | 10 | 4 | 20 |

Fail behavior:

- `RL_FAIL_MODE=open` (default): allow traffic if Redis is unavailable and set `X-RateLimit-Status: degraded`.
- `RL_FAIL_MODE=closed`: return `503 RATE_LIMIT_UNAVAILABLE`.

Example 429 response:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 2
X-RateLimit-Scope: api_key
X-RateLimit-Route-Class: run
X-RateLimit-Retry-After-Ms: 1200

{
  "detail": {
    "code": "RATE_LIMITED",
    "message": "Rate limit exceeded",
    "scope": "api_key",
    "route_class": "run",
    "retry_after_ms": 1200
  }
}
```

## Corpora API

List corpora:

```
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/v1/corpora
```

Get a corpus:

```
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/v1/corpora/c1
```

Patch provider_config_json:

```
curl -s -X PATCH -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/v1/corpora/c1 \
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
  - Set to `http://localhost:8000/v1` to emit versioned audio URLs.

Audio files are stored locally under `var/audio/` (dev-only).

Example `/run` with audio enabled:

```
curl -N -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  -X POST http://localhost:8000/v1/run \
  -d '{
    "session_id":"s-audio-1",
    "corpus_id":"c1",
    "message":"Summarize the demo corpus.",
    "top_k":5,
    "audio":true
  }'
```

SSE events:

- `audio.ready` → `{"type":"audio.ready","request_id":"...","data":{"audio_url":"http://localhost:8000/v1/audio/<id>.mp3","audio_id":"<id>","mime":"audio/mpeg"}}`
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
  http://localhost:8000/v1/documents
```

Ingest raw text (returns `202` with `job_id` + `status_url`):

```
Set `overwrite: true` to requeue a failed or succeeded document with the same `document_id`.
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/v1/documents/text \
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
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/v1/documents/<document_id>
```

List documents:

```
curl -s -H "Authorization: Bearer $API_KEY" http://localhost:8000/v1/documents
```

Reindex a document (returns `202` with `job_id` + `status_url`):

```
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/v1/documents/<document_id>/reindex \
  -d '{
    "chunk_size_chars": 1200,
    "chunk_overlap_chars": 150
  }'
```

Delete a document:

```
curl -s -X DELETE -H "Authorization: Bearer $API_KEY" http://localhost:8000/v1/documents/<document_id>
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
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" http://localhost:8000/v1/ops/health
```

Ingestion stats (last 24 hours by default):

```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" "http://localhost:8000/v1/ops/ingestion?hours=24"
```

Metrics snapshot (JSON):

```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" http://localhost:8000/v1/ops/metrics
```

Heartbeat interpretation:

- `worker_heartbeat_age_s` shows seconds since the last worker heartbeat.
- If the heartbeat is missing or stale, `/ops/health` reports `status: degraded`.

Queue depth:

- `queue_depth` reports pending jobs in the Redis ingestion queue.
- If Redis is unavailable, `queue_depth` is `null` and `/ops/health` reports `redis: degraded`.

## Reliability Controls
Reliability controls are centralized and configurable:
- `EXT_CALL_TIMEOUT_MS` / `EXT_RETRY_*` for external integrations (retrieval, TTS, billing webhooks)
- Circuit breakers per integration (shared via Redis)
- Bulkheads: `RUN_MAX_CONCURRENCY`, `INGEST_MAX_CONCURRENCY`

On saturation, `/v1/run` and ingestion endpoints return `503` with `SERVICE_BUSY`.

## SLO & Error Budget
Fetch current SLO status:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/slo"
```

Example response:
```
{
  "data":{
    "window":"1h",
    "availability":99.95,
    "p95":{"run":2500,"api":620,"documents_text":480},
    "error_budget":{"remaining_pct":87.2,"burn_rate_5m":1.4},
    "status":"healthy"
  },
  "meta":{...}
}
```

## Rollout Controls
Kill switches and canary percentages are managed under `/v1/admin/rollouts/*`.

Kill switch patch:
```
curl -s -X PATCH -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"kill_switches":{"kill.run":true}}' \
  "http://localhost:8000/v1/admin/rollouts/killswitches"
```

Canary patch:
```
curl -s -X PATCH -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"canary_percentages":{"rollout.tts":5}}' \
  "http://localhost:8000/v1/admin/rollouts/canary"
```

## Maintenance Tasks
Admin maintenance endpoint:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/maintenance/run?task=prune_idempotency"
```

Available maintenance tasks:
- `prune_idempotency`
- `prune_audit`
- `cleanup_actions`
- `prune_usage`
- `backup_create_scheduled`
- `backup_prune_retention`
- `restore_drill_scheduled`
- `compliance_evaluate_scheduled`
- `compliance_bundle_periodic`
- `compliance_prune_old_evidence`

Retention knobs:
- `AUDIT_RETENTION_DAYS`
- `UI_ACTION_RETENTION_DAYS`
- `USAGE_COUNTER_RETENTION_DAYS`
- `BACKUP_RETENTION_DAYS`

Runbooks live under `docs/runbooks/`:
- `incident-response.md`
- `breaker-playbook.md`
- `rollout-playbook.md`
- `dr-backup-restore.md`
- `restore-drill-checklist.md`
- `key-rotation-for-backups.md`
- `failover-execution.md`
- `failover-rollback.md`
- `split-brain-mitigation.md`
- `dsar-handling.md`
- `legal-hold-procedure.md`
- `retention-and-anonymization.md`
- `audit-evidence-export.md`
- `key-rotation-execution.md`
- `key-compromise-response.md`
- `kms-outage-procedure.md`
- `encrypted-artifact-access.md`
- `soc2-audit-prep.md`
- `compliance-control-failure-response.md`
- `evidence-bundle-verification.md`
- `compliance-scheduling-and-retention.md`

## Disaster Recovery
Backups include a database logical dump, schema-only dump, and a metadata snapshot.

Backup configuration:
- `BACKUP_ENABLED`, `BACKUP_LOCAL_DIR`
- `BACKUP_ENCRYPTION_ENABLED`, `BACKUP_ENCRYPTION_KEY`
- `BACKUP_SIGNING_ENABLED`, `BACKUP_SIGNING_KEY`
- `BACKUP_RETENTION_DAYS`, `BACKUP_SCHEDULE_CRON`
- `RESTORE_REQUIRE_SIGNATURE`

Create a backup:
```
docker compose exec api python scripts/backup_create.py --type all
```

Restore (dry-run):
```
docker compose exec api python scripts/backup_restore.py \
  --manifest ./backups/<job>/manifest.json \
  --components all \
  --dry-run
```

Restore (destructive requires explicit confirmation):
```
docker compose exec api python scripts/backup_restore.py \
  --manifest ./backups/<job>/manifest.json \
  --components db,schema \
  --allow-destructive
```

Check DR readiness:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/dr/readiness"
```

## Multi-Region Failover
Failover control plane is region-aware and token-gated to reduce accidental promotions.

Key settings:
- `REGION_ID`, `REGION_ROLE`
- `FAILOVER_ENABLED`, `FAILOVER_MODE`
- `REPLICATION_LAG_MAX_SECONDS`, `REPLICATION_HEALTH_REQUIRED`
- `WRITE_FREEZE_ON_UNHEALTHY_REPLICA`
- `FAILOVER_COOLDOWN_SECONDS`, `FAILOVER_TOKEN_TTL_SECONDS`
- `PEER_REGIONS_JSON`

Failover states:
- `idle`
- `freeze_writes`
- `precheck`
- `promoting`
- `verification`
- `completed`
- `failed`
- `rollback_pending`
- `rolled_back`

Safety invariants:
- one failover at a time (Redis lock + DB row lock)
- cooldown enforced between transitions
- promotion/rollback requires one-time short-lived token
- writes freeze when region is not active primary or freeze flag is enabled

Get failover status:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/failover/status"
```

Check failover readiness:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/failover/readiness"
```

Request promotion token:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"purpose":"promote","reason":"primary unavailable"}' \
  "http://localhost:8000/v1/ops/failover/request-token"
```

Promote with token:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"target_region":"ap-southeast-1","token":"<TOKEN>","reason":"incident failover","force":false}' \
  "http://localhost:8000/v1/ops/failover/promote"
```

Toggle write freeze:
```
curl -s -X PATCH -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"freeze":true,"reason":"replication degraded"}' \
  "http://localhost:8000/v1/ops/failover/freeze-writes"
```

## Governance & Compliance
Governance controls add tenant-scoped retention, legal hold, DSAR execution, and policy-as-code decisions.

### Retention Policy Model
- `messages_ttl_days`
- `checkpoints_ttl_days`
- `audit_ttl_days`
- `documents_ttl_days`
- `backups_ttl_days`
- `hard_delete_enabled`
- `anonymize_instead_of_delete`

Read/update retention policy:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/governance/retention/policy"
```

```
curl -s -X PATCH -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"documents_ttl_days":30,"hard_delete_enabled":false,"anonymize_instead_of_delete":true}' \
  "http://localhost:8000/v1/admin/governance/retention/policy"
```

Run retention and fetch report:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/governance/retention/run?tenant_id=t1"
```

```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/governance/retention/report?tenant_id=t1&run_id=1"
```

### Legal Hold Behavior
- Active legal holds supersede retention deletion and DSAR destructive requests.
- Holds can be scoped to `tenant`, `document`, `session`, `user_key`, or `backup_set`.

Create/release legal hold:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"scope_type":"document","scope_id":"doc_123","reason":"Litigation case #123"}' \
  "http://localhost:8000/v1/admin/governance/legal-holds"
```

```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/governance/legal-holds/1/release"
```

### DSAR Workflow
- Create request: `POST /v1/admin/governance/dsar`
- Poll request: `GET /v1/admin/governance/dsar/{id}`
- Download export artifact: `GET /v1/admin/governance/dsar/{id}/artifact`

DSAR export example:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"request_type":"export","subject_type":"session","subject_id":"s1","reason":"Data subject request"}' \
  "http://localhost:8000/v1/admin/governance/dsar"
```

### Policy-as-Code Overview
Policies evaluate by `rule_key` with descending priority and deterministic tie-break by rule id.

Policy rule example:
```
{
  "rule_key": "documents.delete",
  "enabled": true,
  "priority": 1000,
  "condition_json": {"method": "DELETE", "endpoint_prefix": "/v1/documents/"},
  "action_json": {"type": "deny", "code": "POLICY_DENIED", "message": "Delete disabled by policy"}
}
```

Create/list policies:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"rule_key":"documents.delete","priority":1000,"condition_json":{"method":"DELETE"},"action_json":{"type":"deny","code":"POLICY_DENIED"}}' \
  "http://localhost:8000/v1/admin/governance/policies"
```

```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/governance/policies"
```

### Governance Ops Endpoints
Status:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/governance/status"
```

Evidence bundle metadata:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/governance/evidence?window_days=30"
```

### Governance Error Codes
- `POLICY_DENIED` (403)
- `LEGAL_HOLD_ACTIVE` (409)
- `DSAR_REQUIRES_APPROVAL` (409)
- `DSAR_NOT_FOUND` (404)
- `GOVERNANCE_REPORT_UNAVAILABLE` (503)

## Encryption & Key Management
Sensitive artifacts are protected with envelope encryption (AES-256-GCM) using per-tenant key versions.

### Key Settings
- `CRYPTO_ENABLED`, `CRYPTO_PROVIDER`
- `CRYPTO_REQUIRE_ENCRYPTION_FOR_SENSITIVE`
- `CRYPTO_DEFAULT_KEY_ALIAS`, `CRYPTO_ROTATION_INTERVAL_DAYS`
- `CRYPTO_FAIL_MODE` (open|closed)

Local provider:
- `CRYPTO_PROVIDER=local_kms`
- `CRYPTO_LOCAL_MASTER_KEY` (base64/hex)

### Key Rotation
List keys:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/crypto/keys/{tenant_id}"
```

Rotate and re-encrypt:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"reason":"scheduled rotation","reencrypt":true,"force":false}' \
  "http://localhost:8000/v1/admin/crypto/keys/{tenant_id}/rotate"
```

Rotation job status:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/crypto/rotation-jobs/{job_id}"
```

### Crypto Error Codes
- `ENCRYPTION_REQUIRED` (503)
- `KMS_UNAVAILABLE` (503)
- `KEY_ROTATION_IN_PROGRESS` (409)
- `KEY_ROTATION_FAILED` (500)
- `KEY_NOT_ACTIVE` (409)
- `DECRYPTION_FAILED` (500)
- `CRYPTO_POLICY_DENIED` (403)

## SOC 2 Compliance Automation
SOC 2 controls are evaluated continuously and bundled as signed evidence for auditors.

Baseline controls (automated/hybrid):
- `CC6.1` Access control enforcement
- `CC6.2` API key governance
- `CC7.1` Change management evidence
- `CC7.2` Monitoring and incident response readiness
- `CC8.1` Vulnerability/patch cadence (manual artifact upload)
- `A1.1` Backup + restore drill compliance
- `C1.1` Encryption posture

Evaluate controls:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"window_days":30}' \
  "http://localhost:8000/v1/admin/compliance/evaluate"
```

Generate bundle:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"bundle_type":"soc2_on_demand","period_start":"2026-01-01T00:00:00Z","period_end":"2026-01-31T23:59:59Z"}' \
  "http://localhost:8000/v1/admin/compliance/bundles"
```

CLI bundle generation:
```
docker compose exec api python scripts/compliance_generate_bundle.py \
  --bundle-type soc2_on_demand \
  --period-start 2026-01-01T00:00:00Z \
  --period-end 2026-01-31T23:59:59Z
```

Verify bundle:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/compliance/bundles/{id}/verify"
```

Upload dependency scan artifact:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"artifact_type":"dependency_scan","artifact_uri":"s3://compliance/scans/scan.json"}' \
  "http://localhost:8000/v1/admin/compliance/artifacts"
```

Ops posture:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/compliance/status"
```

Compliance settings:
- `COMPLIANCE_ENABLED`
- `COMPLIANCE_DEFAULT_WINDOW_DAYS`
- `COMPLIANCE_EVAL_CRON`, `COMPLIANCE_BUNDLE_CRON`
- `COMPLIANCE_EVIDENCE_RETENTION_DAYS`
- `COMPLIANCE_SIGNATURE_REQUIRED`
- `COMPLIANCE_EVIDENCE_DIR`

### Compliance Error Codes
- `COMPLIANCE_CONTROL_NOT_FOUND` (404)
- `COMPLIANCE_EVALUATION_FAILED` (500)
- `COMPLIANCE_BUNDLE_BUILD_FAILED` (500)
- `COMPLIANCE_BUNDLE_VERIFY_FAILED` (400)
- `COMPLIANCE_DISABLED` (503)

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
  -X POST http://localhost:8000/v1/run \
  -d '{
    "session_id":"s1",
    "corpus_id":"c1",
    "message":"What is the testing strategy of agent 2.0?",
    "top_k":5,
    "audio":false
  }'
```

If you receive `429 RATE_LIMITED`, back off using the `Retry-After` header and retry.

## Usage Quotas

Usage quotas enforce daily and monthly request caps per tenant. Soft caps emit warnings; hard caps can block or observe overages.

Quota behavior:

- Soft cap (default 80% of limit): request allowed + warning header + event emitted once per period.
- Hard cap: block with `402 QUOTA_EXCEEDED` (when `hard_cap_enabled=true`), or allow with overage event (when `hard_cap_enabled=false`).
- `/run` counts as 3 request units to reflect higher cost.

Quota headers (always included on successful requests):

- `X-Quota-Day-Limit`, `X-Quota-Day-Used`, `X-Quota-Day-Remaining`
- `X-Quota-Month-Limit`, `X-Quota-Month-Used`, `X-Quota-Month-Remaining`
- `X-Quota-SoftCap-Reached`: `true|false`
- `X-Quota-HardCap-Mode`: `enforce|observe`

Example 402 response:

```
HTTP/1.1 402 Payment Required
{
  "detail": {
    "code": "QUOTA_EXCEEDED",
    "message": "Monthly request quota exceeded",
    "period": "month",
    "limit": 10000,
    "used": 10000,
    "remaining": 0
  }
}
```

Admin quota endpoints (admin role only, tenant-scoped):

```
# Get limits
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/quotas/t1

# Update limits
curl -s -X PATCH -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/quotas/t1 \
  -d '{
    "daily_requests_limit": 500,
    "monthly_requests_limit": 10000,
    "soft_cap_ratio": 0.8,
    "hard_cap_enabled": true
  }'

# Usage summary
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/usage/t1?period=month&start=2026-02-01"
```

Billing webhook configuration:

- `BILLING_WEBHOOK_ENABLED=true`
- `BILLING_WEBHOOK_URL=https://billing.example.com/hooks`
- `BILLING_WEBHOOK_SECRET=...`
- `BILLING_WEBHOOK_TIMEOUT_MS=2000`

Webhook signature:

- Header `X-Billing-Signature` is `hex(HMAC_SHA256(secret, raw_body))`.
- Header `X-Billing-Event` includes the event type (e.g., `quota.soft_cap_reached`).

## Plans & Entitlements

Plans assign feature entitlements per tenant. Entitlements are enforced server-side for retrieval providers, TTS, ops/audit access, and provider configuration changes.

Plan matrix:

| Feature | Free | Pro | Enterprise |
| --- | --- | --- | --- |
| Local pgvector retrieval | yes | yes | yes |
| AWS Bedrock KB retrieval | no | no | yes |
| GCP Vertex retrieval | no | yes | yes |
| Text-to-speech (TTS) | no | yes | yes |
| Ops admin access | no | yes | yes |
| Audit access | no | yes | yes |
| Corpora provider config patch | no | yes | yes |
| Billing webhook test | no | yes | yes |
| High quota tier | no | no | yes |
| Enterprise SSO (OIDC) | no | yes | yes |
| SCIM 2.0 provisioning | no | no | yes |
| JIT provisioning | no | no | yes |
| Cost visibility | no | yes | yes |
| Cost controls | no | yes | yes |
| Chargeback reports | no | no | yes |

Entitlement enforcement:

- Retrieval provider selection is validated against `feature.retrieval.*` flags.
- `/run` with `audio=true` requires `feature.tts`.
- `/ops/*` and `/audit/events*` require `feature.ops_admin_access` and `feature.audit_access`.
- `PATCH /corpora/{id}` with provider changes requires `feature.corpora_patch_provider_config`.
- SSO endpoints require `feature.identity.sso` and `SSO_ENABLED=true`.
- SCIM endpoints require `feature.identity.scim` and `SCIM_ENABLED=true`.
- JIT provisioning requires `feature.identity.jit` and `jit_enabled=true` on the provider.
- Cost endpoints require `feature.cost_visibility`, `feature.cost_controls`, and `feature.chargeback_reports` as applicable.

Feature disabled error:

```
HTTP/1.1 403 Forbidden
{
  "error": {
    "code": "FEATURE_NOT_ENABLED",
    "message": "Feature not enabled for tenant plan",
    "details": {
      "feature_key": "feature.tts"
    }
  },
  "meta": {
    "request_id": "req_example",
    "api_version": "v1"
  }
}
```

Admin plan endpoints (admin role only, tenant-scoped):

```
# List plans
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/plans

# Get tenant plan
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/plans/t1

# Assign plan
curl -s -X PATCH -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/plans/t1 \
  -d '{"plan_id":"pro"}'

# Override a feature
curl -s -X PATCH -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/plans/t1/overrides \
  -d '{"feature_key":"feature.tts","enabled":true,"config_json":{"voices":["nova"]}}'
```

## Enterprise Identity (SSO/SCIM)

Enterprise identity features add OIDC-based SSO, SCIM 2.0 provisioning, and JIT user creation.

Key settings:

- `SSO_ENABLED=true`
- `SSO_ALLOWED_REDIRECT_HOSTS=app.example.com,admin.example.com`
- `SSO_STATE_TTL_SECONDS=600`
- `SSO_NONCE_TTL_SECONDS=600`
- `SSO_CLOCK_SKEW_SECONDS=120`
- `SSO_SESSION_TTL_HOURS=8`
- `SSO_PUBLIC_DISCOVERY_ENABLED=false`
- `SCIM_ENABLED=true`
- `SCIM_TOKEN_TTL_DAYS=365`
- `SCIM_DEFAULT_PAGE_SIZE=50`
- `SCIM_MAX_PAGE_SIZE=200`

OIDC provider setup (admin, tenant-scoped):

```
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/identity/providers \
  -d '{
    "type": "oidc",
    "name": "Okta",
    "issuer": "https://example.okta.com/oauth2/default",
    "client_id": "0oa123",
    "client_secret_ref": "OKTA_OIDC_CLIENT_SECRET",
    "auth_url": "https://example.okta.com/oauth2/default/v1/authorize",
    "token_url": "https://example.okta.com/oauth2/default/v1/token",
    "jwks_url": "https://example.okta.com/oauth2/default/v1/keys",
    "scopes_json": ["openid", "profile", "email", "groups"],
    "default_role": "reader",
    "role_mapping_json": {"groups": {"Admins": "admin", "Editors": "editor"}},
    "jit_enabled": true
  }'

curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/identity/providers/$PROVIDER_ID/enable
```

SSO flow (dev mode returns JSON, prod typically uses redirects):

```
# Start the OIDC flow (returns authorize_url or redirects if response_mode=redirect)
curl -s "http://localhost:8000/v1/auth/sso/oidc/$PROVIDER_ID/start"

# Callback (normally invoked by IdP)
curl -s "http://localhost:8000/v1/auth/sso/oidc/$PROVIDER_ID/callback?code=AUTH_CODE&state=STATE"
```

SCIM provisioning (token-based):

```
# Create a SCIM token
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/identity/scim/token/create

# Provision a user
curl -s -X POST -H "Authorization: Bearer $SCIM_TOKEN" \
  http://localhost:8000/v1/scim/v2/Users \
  -d '{
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
    "userName": "user@example.com",
    "displayName": "User Example",
    "emails": [{"value": "user@example.com", "primary": true}],
    "active": true
  }'
```

Role mapping examples:

- Claim-based: `{"groups": {"Admins": "admin", "Editors": "editor"}}`
- Single claim: `{"claim": "roles", "mapping": {"staff": "reader"}}`

Token rotation guidance:

1. Create a new SCIM token with `/v1/admin/identity/scim/token/create`.
2. Update the IdP provisioning connector to use the new token.
3. Revoke the old token with `/v1/admin/identity/scim/token/revoke`.

Security notes:

- Client secrets are referenced via `client_secret_ref`; plaintext secrets are never stored.
- ID tokens, access tokens, and SCIM bearer tokens are never logged or persisted.
- Callback URLs must be HTTPS in non-dev environments.
- State and nonce values are stored in Redis with TTLs to prevent replay.

## Cost Governance & Chargeback

Cost governance provides request-level metering, tenant budgets, and chargeback reporting with runtime guardrails.

Key settings:

- `COST_GOVERNANCE_ENABLED=true`
- `COST_DEFAULT_WARN_RATIO=0.8`
- `COST_DEFAULT_HARD_CAP_MODE=block`
- `COST_DEGRADE_ENABLE_TTS_DISABLE=true`
- `COST_DEGRADE_MIN_TOP_K=3`
- `COST_DEGRADE_MAX_OUTPUT_TOKENS=512`
- `COST_ESTIMATOR_ENABLED=true`
- `COST_ESTIMATOR_TOKEN_CHARS_RATIO=4.0`
- `COST_TIMESERIES_DEFAULT_DAYS=30`

Budget model and modes:

- `warn_ratio` triggers `X-Cost-Status: warn` headers and `cost.warn` SSE events without blocking.
- `enforce_hard_cap=true` plus `hard_cap_mode=block|degrade` controls whether requests are blocked or downgraded.
- Degrade mode disables audio first, reduces `top_k`, forces local retrieval, and shortens max output tokens.

Cost headers on successful responses:

- `X-Cost-Month-Budget-Usd`
- `X-Cost-Month-Spend-Usd`
- `X-Cost-Month-Remaining-Usd`
- `X-Cost-Status` (`ok|warn|capped|degraded`)
- `X-Cost-Estimated` (`true|false`)

Pricing catalog (admin, tenant-scoped):

```
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/costs/pricing/catalog \
  -d '{
    "version": "v2026.02",
    "provider": "internal",
    "component": "llm",
    "rate_type": "per_1k_tokens",
    "rate_value_usd": 0.0025,
    "effective_from": "2026-02-01T00:00:00Z",
    "active": true
  }'
```

Budget configuration (admin):

```
curl -s -X PATCH -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/costs/budget \
  -d '{"monthly_budget_usd":500,"warn_ratio":0.8,"enforce_hard_cap":true,"hard_cap_mode":"degrade"}'
```

Chargeback reports:

```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/costs/chargeback/generate?period_start=2026-02-01T00:00:00Z&period_end=2026-03-01T00:00:00Z"

curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/costs/chargeback/reports
```

Self-serve dashboards:

- `GET /v1/self-serve/costs/budget`
- `GET /v1/self-serve/costs/spend/summary`
- `GET /v1/self-serve/costs/spend/timeseries`
- `GET /v1/self-serve/costs/spend/breakdown`
- `GET /v1/self-serve/costs/chargeback/latest`

Security notes:

- Cost metadata is redacted to counts/identifiers; raw prompts and document content are never stored.
- Metering is best-effort and never blocks requests if cost writes fail.

## SLA Policy Engine & Adaptive Autoscaling

Phase 34 adds a tenant-scoped SLA control plane with policy evaluation, runtime enforcement, incidents, and autoscaling recommendations.

Key settings:

- `SLA_ENGINE_ENABLED=true`
- `SLA_DEFAULT_ENFORCEMENT_MODE=observe`
- `SLA_DEFAULT_BREACH_WINDOWS=3`
- `SLA_MEASUREMENT_WINDOW_SECONDS=60`
- `SLA_ERROR_BUDGET_WINDOW_MINUTES=60`
- `SLA_SHED_ENABLED=true`
- `SLA_DEGRADE_TTS_DISABLE=true`
- `SLA_DEGRADE_TOP_K_FLOOR=3`
- `SLA_DEGRADE_MAX_OUTPUT_TOKENS=512`
- `AUTOSCALING_ENABLED=true`
- `AUTOSCALING_DRY_RUN=true`
- `AUTOSCALING_HYSTERESIS_PCT=10`
- `AUTOSCALING_EXECUTOR=noop`

Decision order:

```text
measurements/signals -> policy evaluator -> status(healthy|warning|breached)
-> enforcement decision(allow|warn|degrade|shed) -> runtime headers/SSE/audit
```

Runtime effects:

- `observe`: evaluate only; request continues.
- `warn`: request continues with `X-SLA-*` headers and `sla.warn` SSE.
- `degrade`: request continues with mitigations (disable audio, lower `top_k`, cap output tokens, provider fallback) and `sla.degrade.applied`.
- `shed`: request is rejected with `503` and `SLA_SHED_LOAD`, plus `sla.shed` SSE.

SLA headers:

- `X-SLA-Status` (`healthy|warning|breached`)
- `X-SLA-Policy-Id`
- `X-SLA-Decision` (`allow|warn|degrade|shed`)
- `X-SLA-Route-Class`
- `X-SLA-Window-End`

Create policy example:

```bash
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/sla/policies \
  -d '{
    "name":"enterprise-run-sla",
    "tier":"enterprise",
    "enabled":true,
    "version":1,
    "config_json":{
      "objectives":{
        "availability_min_pct":99.9,
        "p95_ms_max":{"run":1200},
        "p99_ms_max":{"run":2000},
        "max_error_budget_burn_5m":2.0
      },
      "enforcement":{
        "mode":"enforce",
        "breach_window_minutes":5,
        "consecutive_windows_to_trigger":3
      },
      "mitigation":{
        "allow_degrade":true,
        "disable_tts_first":true,
        "reduce_top_k_floor":3,
        "cap_output_tokens":512,
        "provider_fallback_order":["local_pgvector"]
      },
      "autoscaling_link":{"profile_id":null}
    }
  }'
```

Dry-run autoscaling recommendation:

```bash
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/sla/autoscaling/evaluate \
  -d '{
    "profile_id":"profile_123",
    "route_class":"run",
    "current_replicas":2,
    "p95_ms":1650,
    "queue_depth":24,
    "signal_quality":"ok"
  }'
```

## Alerting & Incidents

Phase 37 adds deterministic alert-rule evaluation, incident automation, and operator response workflows.

Key settings:

- `ALERTING_ENABLED=true`
- `OPERABILITY_BACKGROUND_EVALUATOR_ENABLED=true`
- `OPERABILITY_EVAL_INTERVAL_S=30`
- `INCIDENT_AUTOMATION_ENABLED=true`
- `INCIDENT_AUTO_OPEN_MIN_SEVERITY=high`
- `NOTIFY_WEBHOOK_URLS_JSON=["https://.../hook"]` (global fallback only)
- `NOTIFY_MAX_ATTEMPTS=5`
- `NOTIFY_BACKOFF_MS=500`
- `NOTIFY_BACKOFF_MAX_MS=15000`
- `NOTIFY_MAX_AGE_SECONDS=86400`
- `NOTIFY_DEDUPE_WINDOW_S=300`
- `NOTIFY_QUEUE_NAME=notifications`
- `OPS_FORCED_FLAG_TTL_S=900`
- `OPS_FORCED_WRITER_LEASE_TTL_S=30`

Worker services:

```bash
docker compose up -d operability_worker notification_worker notify_receiver
docker compose logs --tail=200 operability_worker
docker compose logs --tail=200 notification_worker
docker compose logs --tail=200 notify_receiver
```

List and tune alert rules:

```bash
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/alerts/rules

curl -s -X PATCH -H "Authorization: Bearer $ADMIN_API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/admin/alerts/rules/$RULE_ID \
  -d '{"enabled":true,"thresholds_json":{"value":2.0}}'
```

Evaluate alerts and inspect triggered rows:

```bash
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/alerts/evaluate?window=5m"
```

Incident lifecycle:

```bash
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/incidents?status=open"

curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/admin/incidents/$INCIDENT_ID/ack \
  -d '{"note":"Acknowledged by on-call"}'

curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/incidents/$INCIDENT_ID/timeline
```

Notification queue triage:

```bash
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/notifications/jobs?status=retrying"

curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/notifications/jobs/$JOB_ID/retry-now

curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/notifications/jobs/$JOB_ID/attempts"
```

Tenant notification destinations:

```bash
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/admin/notifications/destinations \
  -d '{
    "tenant_id":"t1",
    "url":"https://example.com/webhook",
    "headers_json":{"X-Env":"prod"},
    "secret":"replace-with-shared-secret"
  }'

curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/notifications/destinations?tenant_id=t1"
```

Notification routing policies:

- Route matching fields: `event_type`, `severity`, optional `source`, optional `category`.
- Matching supports exact values, arrays, and wildcard `*` for `event_type`.
- Matching routes are evaluated by `priority` (lower value first), then route destination order.
- If no route matches: fallback is tenant enabled destinations, then `NOTIFY_WEBHOOK_URLS_JSON`.
- Delivery is at-least-once; receivers should dedupe using `X-Notification-Id`.

Notification delivery contract:

- `X-Notification-Id`: stable per job id.
- `X-Notification-Attempt`: 1-based delivery attempt number.
- `X-Notification-Event-Type`: event type (for example `incident.opened`).
- `X-Notification-Tenant-Id`: tenant context for receiver-side routing.
- `X-Notification-Signature`: optional `sha256=<hex>` HMAC over raw JSON body when destination secret is configured.
- `X-Notification-Id` is regenerated on DLQ replay because replay creates a new job id.
- Payloads are serialized deterministically and each attempt stores `payload_sha256` for forensic verification.
- Retry semantics: exponential backoff + deterministic jitter, capped by `NOTIFY_MAX_ATTEMPTS`.
- Max age policy: jobs older than `NOTIFY_MAX_AGE_SECONDS` move to DLQ with reason `expired`.

Receiver contract + E2E:

- Use `docs/runbooks/notification-receiver-contract.md` as the receiver implementation baseline.
- Reference receiver service runs at `http://localhost:9001`.
- Receiver knobs:
  - `RECEIVER_SHARED_SECRET`
  - `RECEIVER_REQUIRE_SIGNATURE`
  - `RECEIVER_FAIL_MODE=never|always|first_n`
  - `RECEIVER_FAIL_N`
- Run deterministic sender↔receiver validation:

```bash
docker compose exec api make notify-e2e
```

```bash
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" -H "Content-Type: application/json" \
  http://localhost:8000/v1/admin/notifications/routes \
  -d '{
    "tenant_id":"t1",
    "name":"critical-incidents",
    "enabled":true,
    "priority":10,
    "match_json":{"event_type":["incident.opened"],"severity":["high","critical"]},
    "destinations_json":[{"destination_id":"DESTINATION_ID_1"},{"destination_id":"DESTINATION_ID_2"}]
  }'

curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/notifications/routes?tenant_id=t1"
```

DLQ and replay:

```bash
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/notifications/jobs?tenant_id=t1&status=dlq"

curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/admin/notifications/dlq?tenant_id=t1"

curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/admin/notifications/dlq/$DLQ_ID/replay
```

Operability summary:

```bash
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/ops/operability

curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/ops/notifications
```

Operator actions (`Idempotency-Key` required):

```bash
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" -H "Idempotency-Key: op-1" \
  http://localhost:8000/v1/admin/ops/actions/disable-tts
```

Git publish diagnostics:

```bash
./scripts/git_network_diag.sh
```

See `docs/runbooks/github-push-troubleshooting.md` for HTTPS/SSH fallback workflows.

## Preflight & GA Checklist

Run deploy preflight checks:

```bash
make preflight
```

Generate GA readiness artifacts:

```bash
make ga-checklist
```

Artifacts are written under `var/ops/` by default:

- `preflight.json`
- `ga-checklist-<timestamp>.json`
- `ga-checklist-<timestamp>.md`

## Tenant Self-Serve API

Tenant self-serve endpoints let admins manage API keys, view usage, and request plan upgrades without platform intervention.

Self-serve API key lifecycle:

```
# Create key (plaintext returned once)
curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/self-serve/api-keys \
  -d '{"name":"ci-bot","role":"editor"}'

# List keys (no secrets)
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/self-serve/api-keys

# Revoke key (idempotent)
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/self-serve/api-keys/$KEY_ID/revoke
```

Usage dashboard:

```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/self-serve/usage/summary?window_days=30"

curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/self-serve/usage/timeseries?metric=requests&granularity=day&days=30"
```

Plan visibility and upgrades:

```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/self-serve/plan

curl -s -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/self-serve/plan/upgrade-request \
  -d '{"target_plan":"pro","reason":"Need TTS and Bedrock"}'
```

Billing webhook test (feature-gated):

```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  http://localhost:8000/v1/self-serve/billing/webhook-test
```

Note: plaintext API keys are returned once on creation and must be stored securely by the client.

## SDKs

Generated SDKs live under:

- `sdk/typescript/`
- `sdk/python/`
- `sdk/frontend/` (frontend BFF + SSE helpers)

Regenerate from OpenAPI:

```
make sdk-generate
```

TypeScript (fetch) example:

```
import { createClient } from "./sdk/typescript/client";

const api = await createClient({
  apiKey: process.env.NEXUSRAG_API_KEY!,
  basePath: "http://localhost:8000",
});

const health = await api.healthHealthGet();
```

Python example:

```
import sys
from pathlib import Path

sys.path.append(str(Path("sdk/python/generated")))
sys.path.append(str(Path("sdk/python")))

from client import create_client

api = create_client(api_key="your_api_key", base_url="http://localhost:8000")
health = api.health_health_get()
```

Frontend SDK example:

```
import { UiClient, buildQuery, connectRunStream } from "./sdk/frontend/src";

const client = new UiClient({
  baseUrl: "http://localhost:8000",
  apiKey: process.env.NEXUSRAG_API_KEY!,
});

const docs = await client.listDocuments(buildQuery({ limit: 25, sort: "-created_at" }));

connectRunStream({
  baseUrl: "http://localhost:8000",
  apiKey: process.env.NEXUSRAG_API_KEY!,
  body: { session_id: "s1", corpus_id: "c1", message: "Hello", top_k: 5 },
  onEvent: ({ data }) => console.log(data),
});
```

## Performance Engineering

Phase 35 adds a reproducible performance suite under `tests/perf/` with deterministic and integration execution modes.

Deterministic perf mode:

- `PERF_MODE_ENABLED=true`
- `PERF_FAKE_PROVIDER_MODE=true`
- `LLM_PROVIDER=fake`
- `INGEST_EXECUTION_MODE=inline`

Integration perf mode:

- uses real runtime components (API + Redis + Postgres + worker)
- keeps workload shapes deterministic while exercising full queue/worker paths

Quickstart:

```
# deterministic gates + scenario artifacts
docker compose exec api make perf-test

# markdown summary from latest JSON artifacts
docker compose exec api make perf-report

# short soak (15 minutes)
docker compose exec api python tests/perf/scenarios/run_mixed.py --duration 900 --deterministic
```

Perf artifacts:

- JSON/markdown reports: `tests/perf/reports/`
- gate output: `tests/perf/reports/perf-gates-latest.json`
- rollup summary: `tests/perf/reports/perf-summary-latest.md`

Interpreting reports:

- `route_class.p95_ms` and `route_class.p99_ms` capture end-to-end latency.
- `sse.first_token_p95_ms` tracks time-to-first-token for `/v1/run`.
- `extra.ingest_queue_wait_p95_ms` tracks ingestion backlog pressure.
- `extra.noisy_neighbor_success_ratio` captures multi-tenant fairness.

Capacity model:

- `python3 scripts/capacity_estimate.py --headroom 0.30`
- Outputs:
  - `docs/capacity-model.md`
  - `tests/perf/reports/capacity-model.json`

## Notes

- `/run` emits `request.accepted`, `token.delta`, `message.final`, optional `audio.*`, and `done` events with a monotonic `seq`.
- Heartbeat events are emitted for long streams (`event: heartbeat`).
- If Vertex credentials/config are missing, `/run` emits an SSE `error` event with a clear message.
- Retrieval uses a deterministic fake embedding (no external embedding APIs).
- Set `DEBUG_EVENTS=true` to emit `debug.retrieval` SSE events after retrieval for validation.

## Validation Checklist

1) Copy env file:

```
cp .env.example .env
```

1) Start services:

```
docker compose up --build -d
```

1) Run migrations:

```
docker compose exec api alembic upgrade head
```

1) Create an API key:

```
docker compose exec api python scripts/create_api_key.py --tenant t1 --role admin --name local-admin
```

1) Export the key:

```
export API_KEY=<api_key_from_script>
```

1) Health check:

```
curl -s http://localhost:8000/v1/health
```

1) Seed demo data:

```
docker compose exec api python scripts/seed_demo.py
```

1) SSE run (expect `request.accepted`, `token.delta`, `message.final`, optional `audio.*`, and `done`):

```
curl -N -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
  -X POST http://localhost:8000/v1/run \
  -d '{
    "session_id":"s1",
    "corpus_id":"c1",
    "message":"What is the testing strategy of agent 2.0?",
    "top_k":5,
    "audio":false
  }'
```

1) Run tests in container:

```
docker compose exec api pytest -q
```

## Retrieval sanity check

This query should match seeded content about testing strategy and release gates:

```
curl -N -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -X POST http://localhost:8000/v1/run \
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
make perf-test
make perf-report
make sdk-generate
make security-audit
make security-lint
make security-secrets-scan
make compliance-snapshot
make lint
make typecheck
make secrets-scan
make sca
```

## Security & Compliance

Security/compliance checks and evidence automation are available locally and in CI:

```
make security-audit
make security-lint
make security-secrets-scan
make compliance-snapshot TENANT_ID=t1 ACTOR_ID=admin
make lint
make typecheck
make secrets-scan
make sca
```

Compliance snapshot/bundle APIs:

- `POST /v1/admin/compliance/snapshot`
- `POST /v1/admin/compliance/snapshots`
- `GET /v1/admin/compliance/snapshots?limit=20`
- `GET /v1/admin/compliance/snapshots/{id}`
- `GET /v1/admin/compliance/bundle/{snapshot_id}.zip`
- `GET /v1/admin/compliance/snapshots/{snapshot_id}/download`

API key lifecycle admin APIs:

- `GET /v1/admin/api-keys?tenant_id=t1`
- `PATCH /v1/admin/api-keys/{id}`

Keyring admin APIs:

- `GET /v1/admin/keyring`
- `POST /v1/admin/keyring/rotate?purpose=signing|encryption|backup_signing|backup_encryption|webhook_signing`
- `POST /v1/admin/keyring/{key_id}/retire`

Keyring enforcement behavior:

- `KEYRING_MASTER_KEY_REQUIRED=true` fails closed for key rotation with `KEYRING_NOT_CONFIGURED` when `KEYRING_MASTER_KEY` is missing.
- `KEYRING_MASTER_KEY_REQUIRED=false` keeps keyring optional for local/dev; rotation returns `KEYRING_DISABLED` if no key source is configured.
- Evidence bundles use redacted config only and never decrypt key material.

API key inactivity enforcement:

- `AUTH_API_KEY_INACTIVE_ENFORCED=true` and `AUTH_API_KEY_INACTIVE_DAYS=<N>` enforce stale-key denial in auth (`AUTH_INACTIVE_KEY`).
- Revoked keys return `AUTH_REVOKED_KEY`; expired keys return `AUTH_EXPIRED_KEY`.
- `PATCH /v1/admin/api-keys/{id}` with `{"active": true}` reactivates a key and resets `last_used_at` as the inactivity anchor.

Retention proof APIs:

- `POST /v1/admin/governance/retention/run?task=prune_all`
- `GET /v1/admin/governance/retention/status`

Bundle contents:

- `snapshot.json`
- `controls.json`
- `config_sanitized.json` (secrets redacted)
- `runbooks_index.json`
- `changelog_excerpt.md`
- `capacity_model_excerpt.md`
- `perf_gates_excerpt.json`
- `perf_report_summary.md`
- `ops_metrics_24h_summary.json`

Compliance snapshot canonical fields:

- `captured_at` is the canonical capture timestamp (legacy `created_at` is still returned for compatibility).
- `results_json` contains normalized evaluation output.
- `artifact_paths_json` persists generated bundle metadata (`bundle_path`, `bundle_download_path`, timestamps).

CLI helpers:

- `python scripts/rotate_api_key.py <old_key_id> [--keep-old-active]`
- `python scripts/list_api_keys.py --tenant t1 --inactive-only`

## Release process

- Branch naming: `feat/<short-scope>` or `fix/<short-scope>`
- Bump version: update `pyproject.toml` and add a new entry in `CHANGELOG.md`
- Tag release: `git tag vX.Y.Z`
- Use the repo's default branch name (e.g., `main`); do not assume a specific remote.
