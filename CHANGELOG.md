# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

- None.

## 2.1.0 - 2026-02-15

- Added enterprise identity models for IdPs, tenant users, SCIM provisioning, and SSO sessions.
- Added OIDC SSO flow with PKCE, state/nonce replay protection, and JIT provisioning support.
- Added SCIM 2.0 provisioning endpoints with token-based auth and audit events.
- Added identity admin APIs for provider, token, and tenant user management.
- Added entitlements, configuration, tests, and runbooks for enterprise identity.

## 2.0.0 - 2026-02-15

- Added SOC 2 control catalog with continuous evaluation engine.
- Added evidence bundle generation/signing/verification and compliance admin APIs.
- Added compliance ops posture endpoint, scheduling tasks, and retention pruning.
- Added SOC 2 runbooks and compliance tests.

## 1.9.0 - 2026-02-15

- Added tenant key registry and encrypted blob store for sensitive artifacts.
- Added envelope encryption with pluggable KMS providers and crypto error contracts.
- Added key rotation APIs with resumable re-encryption jobs and telemetry.
- Added crypto posture to governance status plus crypto runbooks and tests.

## 1.8.0 - 2026-02-14

- Added governance data model for retention policies, legal holds, DSAR requests, and policy rules.
- Added policy-as-code engine with deterministic rule evaluation and destructive action enforcement.
- Added retention pipeline execution/reporting with legal hold supersession and anonymize/hard-delete modes.
- Added DSAR APIs for export/delete/anonymize with artifact generation and auditable lifecycle states.
- Added governance ops status/evidence endpoints plus governance runbooks and tests.

## 1.7.0 - 2026-02-14

- Added region status and failover control plane tables/endpoints.
- Added readiness arbitration with blockers, split-brain detection, and recommendations.
- Added token-gated promotion/rollback flows with cooldown and concurrency guards.
- Added write-freeze enforcement for mutation and run paths during failover/degraded states.
- Added failover telemetry, audit events, and operator runbooks.

## 1.6.0 - 2026-02-10

- Added DR backup/restore tooling with signed manifests.
- Added DR readiness/backups/restore-drill ops endpoints.
- Added backup retention pruning and drill reporting.
- Added DR runbooks and tests.

## 1.5.0 - 2026-02-09

- Added reliability controls: retries, circuit breakers, bulkheads.
- Added `/v1/ops/slo` with availability, latency, and error budget indicators.
- Added rollout kill switches and canary controls.
- Added maintenance tasks and runbooks for incident response and rollouts.

## 1.4.0 - 2026-02-09

- Added `/v1/ui` BFF endpoints for bootstrap, dashboard, documents, activity, and actions.
- Added standardized cursor/filter/sort query contracts for UI lists.
- Added optimistic UI action contract and persisted UI action records.
- Added SSE sequence + heartbeat protocol and reconnect semantics for `/v1/run`.
- Added frontend TypeScript integration SDK with helpers and examples.

## 1.3.0 - 2026-02-09

- Added `/v1` versioned API routes with legacy deprecation headers.
- Standardized success/error envelopes for versioned JSON endpoints.
- Added idempotency-key support for write endpoints with conflict detection.
- Improved OpenAPI schemas and examples plus generated SDK scaffolding.
- Added contract tests for envelopes, idempotency, and compatibility headers.

## 1.2.0 - 2026-02-09

- Added tenant self-serve API key lifecycle endpoints.
- Added usage summary and timeseries endpoints for tenant dashboards.
- Added plan visibility and upgrade request workflow.
- Added billing webhook test endpoint (feature-gated).
- Added audit events for self-serve operations.

## 1.1.0 - 2026-02-09

- Added tenant plan assignments and feature entitlements.
- Added server-side feature gating for retrieval providers, TTS, ops/audit, and corpora patching.
- Added admin APIs for plan assignment and overrides.
- Added entitlement tests and documentation.

## 1.0.0 - 2026-02-07

- Added tenant quotas with daily/monthly limits and soft/hard cap modes.
- Added quota response headers and 402 QUOTA_EXCEEDED contract.
- Added admin quota management and usage summary endpoints.
- Added billing webhook hooks for quota events (best-effort).

## 0.9.0 - 2026-02-07

- Added Redis-backed token-bucket rate limiting.
- Added per-key and per-tenant dual enforcement with route-class policies.
- Added stable 429 schema with retry hints and throttling headers.
- Added audit events for throttling and degraded mode.

## 0.8.0 - 2026-02-07

- Added audit_events table and central audit service.
- Added auth/security and data mutation event logging across the API.
- Added admin-only audit query endpoints with tenant scoping.
- Implemented metadata redaction policy for sensitive fields.

## 0.7.0 - 2026-02-07

- Added API key authentication with hashed key storage.
- Added RBAC roles and tenant binding from authenticated principals.
- Protected run, documents, corpora, and ops endpoints by role.
- Added API key management scripts for create/revoke workflows.
- Added auth/RBAC integration tests and tenant isolation coverage.

## 0.6.1 - 2026-02-07

- Added ops health and ingestion visibility endpoints.
- Added worker heartbeat reporting and queue depth status.
- Added ingestion metrics endpoint for dashboards/alerts.

## 0.6.0 - 2026-02-06

- Added Redis-backed async ingestion worker with ARQ.
- Added enqueue-based API semantics returning 202 Accepted.
- Added document status tracking with failure reasons and timestamps.
- Added worker service to docker-compose for ingestion processing.
- Added integration tests for queued/succeeded/failed lifecycle flows.

## 0.5.0 - 2026-02-06

- Added document lifecycle endpoints (delete, reindex, raw text ingest).
- Added document lifecycle metadata (ingest source, reindex timestamp, storage path).
- Added integration tests for idempotent text ingest, delete, and reindex flows.

## 0.4.0 - 2026-02-02

- Added document ingestion API (upload/status/list) with tenant scoping.
- Added deterministic chunking, embedding, and pgvector storage for ingested documents.
- Added integration tests covering upload → ingest → retrieval.

## 0.3.0 - 2026-02-02

- Added optional TTS with audio.ready SSE events and local /audio serving route.
- Added fake TTS and fake LLM paths for deterministic, no-cloud tests.
- Documented TTS configuration and audio event behavior.

## 0.2.2 - 2026-02-02

- Added provider_smoke script to validate retrieval routing without LLM calls.
- Documented cloud retrieval credentials and troubleshooting guidance.
- Added smoke-script unit tests for error mapping.

## 0.2.1 - 2026-02-02

- Added corpora list/get/patch endpoints with tenant scoping.
- Reused retrieval config validation across API and router.
- Added integration tests for corpora management API.

## 0.2.0 - 2026-02-02

- Added multi-cloud retrieval routing per corpus config.
- Added Bedrock KB and Vertex retrieval adapters (mock-tested).
- Seed demo corpus configured for router defaults.

## 0.1.8 - 2026-02-01

- Made test suite runnable in docker; added pytest dev deps.
- Stabilized integration tests for SSE and persistence without external services.
- Improved unit coverage for embeddings, retrieval, and Vertex provider config.

## 0.1.7 - 2026-02-01

- Improved Vertex Gemini config/auth error mapping.
- Added timeout and cancellation handling for streaming.
- Ensured progressive token streaming with minimal buffering.
- Expanded tests for missing-config provider path.

## 0.1.6 - 2026-02-01

- Enforced pgvector extension via migration for consistent environments.
- Corrected cosine retrieval with similarity scoring and deterministic ordering.
- Added embedding dimension invariants and controlled retrieval errors.
- Expanded tests for embeddings and retrieval invariants.

## 0.1.5 - 2026-02-01

- Hardened DB session lifecycle and explicit transaction boundaries for `/run`.
- Race-safe session upsert with tenant mismatch handling.
- Improved DB error mapping and persistence boundary tests.

## 0.1.4 - 2026-02-01

- Hardened SSE framing and headers.
- Added request_id tracing to all SSE events.
- Improved graceful error and disconnect handling.
- Expanded SSE integration tests.

## 0.1.3 - 2026-02-01

- Added deterministic seed script for demo corpus and chunks.
- Updated README seeding instructions and sanity check.

## 0.1.2 - 2026-02-01

- Add validation checklist commands and clarify release process language.
- Remove obsolete docker compose version field to avoid warnings.

## 0.1.1 - 2026-02-01

- Add release scaffolding, changelog, and documented release process.
