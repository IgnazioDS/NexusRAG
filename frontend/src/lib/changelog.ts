/**
 * Changelog data — derived from CHANGELOG.md. Each release is grouped
 * into a thematic "era" so the timeline reads as a narrative arc:
 *
 *   0.x — Foundation (the agent, retrieval, ingestion, audit log)
 *   1.x — Enterprise primitives (rate limits, quotas, plans, BFF)
 *   1.5+ — Reliability + DR + governance + crypto + failover
 *   2.x — Identity + ABAC + compliance + cost + SLA + perf + alerts
 *   2.8+ — Notification reliability + governance retention proofs
 *   Unreleased — Receiver Contract v1.0 hardening
 */

export type Era =
  | "Unreleased"
  | "Notification reliability"
  | "Compliance + cost + SLA"
  | "Identity + ABAC"
  | "Resilience + crypto"
  | "Reliability + DR"
  | "Enterprise primitives"
  | "Foundation";

export interface Release {
  version: string;
  /** Date in ISO format. "Unreleased" entries omit this. */
  date?: string;
  era: Era;
  /** 1-2 sentence theme summary. */
  theme: string;
  /** Bullet list — short, scannable. */
  highlights: string[];
}

export const RELEASES: Release[] = [
  {
    version: "Unreleased",
    era: "Unreleased",
    theme:
      "Notification Receiver Contract v1.0 — typed headers, canonical signatures, deterministic dedupe.",
    highlights: [
      "Typed header parsing + timestamp skew support",
      "Reusable sqlite dedupe primitives",
      "notify_receiver service hardened with strict verification + /stats + /ops aggregates",
      "Operator targets: make receiver-up, make receiver-stats",
    ],
  },
  {
    version: "2.9.4",
    date: "2026-02-18",
    era: "Notification reliability",
    theme:
      "Receiver contract helpers + reference webhook receiver + E2E tests.",
    highlights: [
      "Signature parsing/verification + payload hashing primitives",
      "Compose-ready notify_receiver with deterministic fail modes",
      "E2E sender↔receiver tests covering happy path, retries, signature rejection, DLQ replay",
      "make notify-e2e + receiver contract runbook",
    ],
  },
  {
    version: "2.9.3",
    date: "2026-02-18",
    era: "Notification reliability",
    theme:
      "Notification delivery contract hardening with HMAC signatures + state machine.",
    highlights: [
      "Deterministic webhook headers + optional HMAC signatures",
      "Attempt-level payload_sha256 persistence",
      "Tightened state machine with CAS claims and DLQ on max-age expiry",
      "Admin notification attempts endpoint + retry-now job control",
    ],
  },
  {
    version: "2.9.2",
    date: "2026-02-18",
    era: "Notification reliability",
    theme:
      "Tenant-scoped notification routing policies + DLQ persistence + admin replay.",
    highlights: [
      "notification_routes table with deterministic matching",
      "notification_dead_letters persistence + admin replay APIs",
      "kill.notifications rollout kill switch for delivery storms",
      "Updated operability docs with route matching + DLQ replay flows",
    ],
  },
  {
    version: "2.9.1",
    date: "2026-02-18",
    era: "Notification reliability",
    theme:
      "Keyring required-only mode + inactive API key denial + compliance snapshot schema.",
    highlights: [
      "KEYRING_MASTER_KEY_REQUIRED with deterministic failure codes",
      "AUTH_INACTIVE_KEY denial path + admin reactivation",
      "Compliance snapshot canonical schema + persisted artifact paths",
    ],
  },
  {
    version: "2.9.0",
    date: "2026-02-18",
    era: "Notification reliability",
    theme:
      "Admin API key lifecycle + keyring contract + governance retention proofs.",
    highlights: [
      "/v1/admin/api-keys lifecycle endpoints (expire/reactivate/revoke)",
      "/v1/admin/keyring expanded purpose support + activation lifecycle",
      "Compliance snapshot contract aliases + persisted evidence bundles under var/evidence",
      "Governance retention-proof APIs + status endpoint",
    ],
  },
  {
    version: "2.8.2",
    date: "2026-02-18",
    era: "Notification reliability",
    theme:
      "Tenant-scoped notification destinations + ARQ-backed delivery worker.",
    highlights: [
      "Notification destination routing with global fallback support",
      "ARQ worker for delivery; jobs/attempts as durable source of truth",
      "Forced control writes hardened with short-lived writer lease",
    ],
  },
  {
    version: "2.8.1",
    date: "2026-02-18",
    era: "Notification reliability",
    theme: "Operability evaluator + durable notification jobs + forced flags.",
    highlights: [
      "Background operability evaluator with distributed locking + heartbeats",
      "Durable notification jobs/attempts with retry backoff + dedupe windows",
      "Versioned forced-control flags with TTL and region-role enforcement",
      "/v1/ops/operability summary endpoint",
    ],
  },
  {
    version: "2.8.0",
    date: "2026-02-18",
    era: "Compliance + cost + SLA",
    theme:
      "Alert rules registry + incident automation lifecycle + operator action APIs.",
    highlights: [
      "Alert rules registry + deterministic evaluation APIs (/v1/admin/alerts/*)",
      "Incident automation lifecycle with timeline (/v1/admin/incidents/*)",
      "Operator action endpoints with idempotency + persisted records",
      "make preflight + make ga-checklist deploy automation",
    ],
  },
  {
    version: "2.7.0",
    date: "2026-02-18",
    era: "Compliance + cost + SLA",
    theme:
      "Compliance control catalog snapshots + API key lifecycle + platform keyring.",
    highlights: [
      "Compliance control catalog snapshots + in-memory evidence bundle exports",
      "API key lifecycle hardening with optional expiration + rotation helper",
      "/v1/admin/keys keyring lifecycle APIs with encrypted-at-rest material",
      "make security-audit / security-lint / security-secrets-scan gates",
    ],
  },
  {
    version: "2.6.0",
    date: "2026-02-17",
    era: "Compliance + cost + SLA",
    theme: "Reproducible perf harness + capacity model + perf gates.",
    highlights: [
      "Reproducible load/soak harness with deterministic perf scenarios",
      "Capacity model + sizing guidance for standard/pro/enterprise tiers",
      "Noisy-neighbor fairness checks + perf report artifacts",
      "Tuned DB pooling controls + detailed timing instrumentation",
    ],
  },
  {
    version: "2.5.0",
    date: "2026-02-17",
    era: "Compliance + cost + SLA",
    theme: "SLA policy engine + adaptive autoscaling.",
    highlights: [
      "SLA policy engine with tenant assignments + incident tracking",
      "Runtime SLA enforcement on /v1/run + ingestion (warn/degrade/shed)",
      "Adaptive autoscaling profiles/actions + admin SLA APIs",
    ],
  },
  {
    version: "2.4.0",
    date: "2026-02-17",
    era: "Compliance + cost + SLA",
    theme: "Cost metering + tenant budgets + chargeback reports.",
    highlights: [
      "Cost metering + pricing catalog",
      "Tenant budgets with warn/block/degrade guardrails",
      "Admin/self-serve spend analytics + chargeback reports",
    ],
  },
  {
    version: "2.3.0",
    date: "2026-02-16",
    era: "Compliance + cost + SLA",
    theme: "Quality datasets + runtime guardrails + release gates.",
    highlights: [
      "Quality datasets/runs/results + metrics trends",
      "Runtime quality guardrails + SSE quality events",
      "Release gate enforcement + override workflow",
    ],
  },
  {
    version: "2.2.0",
    date: "2026-02-15",
    era: "Identity + ABAC",
    theme: "ABAC policy engine + document-level ACLs.",
    highlights: [
      "Priority-aware deny-first / allow ABAC engine",
      "Document-level ACLs with creator-owner default",
      "Admin policy/permission APIs with simulation",
      "Tenant guard / RLS posture checks",
    ],
  },
  {
    version: "2.1.0",
    date: "2026-02-15",
    era: "Identity + ABAC",
    theme: "Enterprise SSO (OIDC) + SCIM 2.0 + identity admin APIs.",
    highlights: [
      "OIDC SSO with PKCE + state/nonce replay protection + JIT provisioning",
      "SCIM 2.0 endpoints with token auth + audit events",
      "Identity admin APIs (provider, token, tenant user)",
      "Entitlements + identity runbooks",
    ],
  },
  {
    version: "2.0.0",
    date: "2026-02-15",
    era: "Identity + ABAC",
    theme:
      "SOC 2 control catalog + continuous evaluation + signed evidence bundles.",
    highlights: [
      "SOC 2 control catalog with continuous evaluation engine",
      "Evidence bundle generation/signing/verification",
      "Compliance ops posture endpoint + scheduling + retention pruning",
      "SOC 2 runbooks + compliance tests",
    ],
  },
  {
    version: "1.9.0",
    date: "2026-02-15",
    era: "Resilience + crypto",
    theme: "Envelope encryption + pluggable KMS + key rotation.",
    highlights: [
      "Tenant key registry + encrypted blob store for sensitive artifacts",
      "Envelope encryption with pluggable KMS providers",
      "Key rotation APIs with resumable re-encryption jobs",
      "Crypto runbooks + governance posture integration",
    ],
  },
  {
    version: "1.8.0",
    date: "2026-02-14",
    era: "Resilience + crypto",
    theme: "Governance data model + DSAR + retention pipeline.",
    highlights: [
      "Retention policies, legal holds, DSAR requests, policy rules",
      "Policy-as-code engine with deterministic rule evaluation",
      "Retention execution/reporting with legal hold supersession",
      "DSAR APIs (export/delete/anonymize) with auditable lifecycle",
    ],
  },
  {
    version: "1.7.0",
    date: "2026-02-14",
    era: "Resilience + crypto",
    theme: "Region status + failover control plane + write-freeze.",
    highlights: [
      "Region status + failover control plane tables/endpoints",
      "Readiness arbitration with split-brain detection",
      "Token-gated promotion/rollback flows + cooldown guards",
      "Write-freeze enforcement during failover",
    ],
  },
  {
    version: "1.6.0",
    date: "2026-02-10",
    era: "Reliability + DR",
    theme: "DR backup/restore tooling with signed manifests.",
    highlights: [
      "DR backup/restore with signed manifests",
      "DR readiness/backups/restore-drill ops endpoints",
      "Backup retention pruning + drill reporting",
      "DR runbooks + tests",
    ],
  },
  {
    version: "1.5.0",
    date: "2026-02-09",
    era: "Reliability + DR",
    theme: "Reliability primitives — retries, circuit breakers, bulkheads.",
    highlights: [
      "Retries + circuit breakers + bulkheads",
      "/v1/ops/slo with availability + latency + error budget",
      "Rollout kill switches + canary controls",
      "Maintenance tasks + incident response runbooks",
    ],
  },
  {
    version: "1.4.0",
    date: "2026-02-09",
    era: "Reliability + DR",
    theme: "BFF endpoints + SSE protocol + frontend SDK.",
    highlights: [
      "/v1/ui BFF endpoints (bootstrap, dashboard, documents, activity, actions)",
      "Standardized cursor/filter/sort query contracts for UI lists",
      "Optimistic UI action contract with persisted records",
      "SSE sequence + heartbeat protocol + reconnect semantics",
      "Frontend TypeScript integration SDK",
    ],
  },
  {
    version: "1.3.0",
    date: "2026-02-09",
    era: "Enterprise primitives",
    theme: "/v1 versioned routes + envelopes + idempotency keys.",
    highlights: [
      "/v1 versioned API with legacy deprecation headers",
      "Standardized success/error envelopes",
      "Idempotency-key support on write endpoints",
      "Improved OpenAPI schemas + generated SDK scaffolding",
    ],
  },
  {
    version: "1.2.0",
    date: "2026-02-09",
    era: "Enterprise primitives",
    theme: "Tenant self-serve APIs + usage analytics + billing webhook.",
    highlights: [
      "Tenant self-serve API key lifecycle endpoints",
      "Usage summary + timeseries endpoints",
      "Plan visibility + upgrade request workflow",
      "Billing webhook test endpoint",
    ],
  },
  {
    version: "1.1.0",
    date: "2026-02-09",
    era: "Enterprise primitives",
    theme: "Plan assignments + entitlements + feature gating.",
    highlights: [
      "Tenant plan assignments + feature entitlements",
      "Server-side feature gating for retrieval/TTS/ops/audit/corpora",
      "Admin APIs for plan assignment + overrides",
    ],
  },
  {
    version: "1.0.0",
    date: "2026-02-07",
    era: "Enterprise primitives",
    theme: "Tenant quotas + 402 QUOTA_EXCEEDED contract + admin management.",
    highlights: [
      "Daily/monthly tenant quotas with soft/hard cap modes",
      "Quota response headers + 402 QUOTA_EXCEEDED contract",
      "Admin quota management + usage summary endpoints",
    ],
  },
  {
    version: "0.9.0",
    date: "2026-02-07",
    era: "Foundation",
    theme: "Redis-backed token-bucket rate limiting.",
    highlights: [
      "Per-key + per-tenant dual enforcement",
      "Stable 429 schema with retry hints",
      "Audit events for throttling + degraded mode",
    ],
  },
  {
    version: "0.8.0",
    date: "2026-02-07",
    era: "Foundation",
    theme: "Audit log + central audit service.",
    highlights: [
      "audit_events table + central audit service",
      "Auth/security/data mutation event logging across the API",
      "Admin-only audit query endpoints with tenant scoping",
      "Metadata redaction policy for sensitive fields",
    ],
  },
  {
    version: "0.7.0",
    date: "2026-02-07",
    era: "Foundation",
    theme: "API key auth + RBAC + tenant binding.",
    highlights: [
      "API key auth with hashed key storage",
      "RBAC roles + tenant binding",
      "Protected run/documents/corpora/ops endpoints by role",
      "Auth/RBAC integration tests + tenant isolation coverage",
    ],
  },
  {
    version: "0.6.x",
    date: "2026-02-06",
    era: "Foundation",
    theme: "Async ARQ ingestion + ops health + worker visibility.",
    highlights: [
      "Redis-backed ARQ ingestion worker",
      "Enqueue-based 202 Accepted ingest semantics",
      "Document status tracking with failure reasons",
      "Worker heartbeats + queue depth status",
    ],
  },
  {
    version: "0.5.0",
    date: "2026-02-06",
    era: "Foundation",
    theme: "Document lifecycle (delete, reindex, raw text ingest).",
    highlights: [
      "Lifecycle endpoints with metadata (source, reindex ts, storage path)",
      "Idempotent text ingest + delete + reindex flows",
    ],
  },
  {
    version: "0.4.0",
    date: "2026-02-02",
    era: "Foundation",
    theme: "Document ingestion API with deterministic chunking + pgvector storage.",
    highlights: [
      "Upload/status/list APIs with tenant scoping",
      "Deterministic chunking + embedding + pgvector storage",
      "Integration tests covering upload → ingest → retrieval",
    ],
  },
  {
    version: "0.2.0",
    date: "2026-02-02",
    era: "Foundation",
    theme: "Multi-cloud retrieval routing per corpus.",
    highlights: [
      "Bedrock KB + Vertex retrieval adapters (mock-tested)",
      "Retrieval routing per corpus.provider_config_json",
      "Seed demo corpus configured for router defaults",
    ],
  },
  {
    version: "0.1.0",
    date: "2026-02-01",
    era: "Foundation",
    theme: "Streaming agent + SSE framing + DB session lifecycle.",
    highlights: [
      "Streaming /v1/run with progressive token streaming",
      "SSE framing + request_id tracing + reconnect semantics",
      "DB session lifecycle hardening + race-safe upserts",
      "pgvector cosine retrieval with similarity scoring",
    ],
  },
];

/** Total release count (excluding Unreleased). */
export const RELEASE_TOTAL = RELEASES.filter((r) => r.version !== "Unreleased").length;
