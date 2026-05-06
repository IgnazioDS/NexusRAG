/**
 * Feature matrix for NexusRAG — derived from README.md "Feature Matrix"
 * section. Organized by capability domain so the dashboard can render
 * grouped views and the reader can scan by interest area.
 *
 * Each entry maps to a real production feature with a config flag and
 * (where applicable) a kill switch. The "since" field references the
 * CHANGELOG version that introduced the feature.
 */

export type FeatureStatus = "live" | "beta" | "preview";

export interface Feature {
  name: string;
  status: FeatureStatus;
  /** Environment variable that gates the feature. */
  flag?: string;
  /** Kill switch flag, when one exists. */
  kill?: string;
  /** Short blurb (1 sentence) for the catalog row. */
  blurb: string;
  /** Version that introduced the feature (e.g. "2.2.0"). */
  since?: string;
}

export interface FeatureCategory {
  /** Stable slug for in-page anchors. */
  id: string;
  label: string;
  /** Tagline shown under the category heading. */
  description: string;
  features: Feature[];
}

export const FEATURE_CATEGORIES: FeatureCategory[] = [
  {
    id: "agent-runtime",
    label: "Agent Runtime",
    description:
      "Streaming LangGraph agent serving the public /v1/run endpoint with SSE.",
    features: [
      {
        name: "Streaming RAG (/v1/run, SSE)",
        status: "live",
        flag: "LLM_PROVIDER",
        blurb:
          "Stateful LangGraph agent with progressive token streaming, request_id tracing, and reconnect semantics.",
        since: "0.1.0",
      },
      {
        name: "Quality guardrails + SSE quality events",
        status: "live",
        flag: "QUALITY_ENABLED",
        blurb:
          "Runtime quality gates emit SSE events; release gates enforce override workflow.",
        since: "2.3.0",
      },
      {
        name: "TTS audio output (OpenAI)",
        status: "live",
        flag: "TTS_PROVIDER=openai",
        blurb:
          "Optional /audio.ready SSE events with deterministic fake-TTS path for tests.",
        since: "0.3.0",
      },
    ],
  },
  {
    id: "retrieval",
    label: "Multi-Cloud Retrieval",
    description:
      "Per-corpus provider routing across pgvector, Bedrock KB, and Vertex AI Search.",
    features: [
      {
        name: "PostgreSQL + pgvector (local)",
        status: "live",
        flag: "DATABASE_URL",
        blurb:
          "Cosine retrieval with similarity scoring, deterministic ordering, and embedding-dimension invariants.",
        since: "0.1.0",
      },
      {
        name: "AWS Bedrock Knowledge Bases",
        status: "live",
        flag: "corpus.provider=aws_bedrock_kb",
        blurb:
          "Retrieval routed to Bedrock KB per corpus config — region + KB id selectable per tenant.",
        since: "0.2.0",
      },
      {
        name: "GCP Vertex AI Search",
        status: "live",
        flag: "corpus.provider=gcp_vertex",
        blurb:
          "Discovery Engine datastores wired through the same router; mock-tested without live creds.",
        since: "0.2.0",
      },
    ],
  },
  {
    id: "auth-identity",
    label: "Auth & Identity",
    description:
      "RBAC + ABAC + document ACLs with default-deny, plus enterprise SSO/SCIM.",
    features: [
      {
        name: "API key auth + RBAC",
        status: "live",
        flag: "AUTH_ENABLED",
        blurb:
          "Hashed key storage; reader/editor/admin role gates on every protected endpoint.",
        since: "0.7.0",
      },
      {
        name: "ABAC policy engine",
        status: "live",
        flag: "AUTHZ_ABAC_ENABLED",
        blurb:
          "Priority-aware deny-first / allow policies with simulation API and DSL conditions.",
        since: "2.2.0",
      },
      {
        name: "Document ACLs",
        status: "live",
        flag: "AUTHZ_DEFAULT_DENY",
        blurb:
          "Per-document grants (read / write / admin) with creator-owner default and expiring grants.",
        since: "2.2.0",
      },
      {
        name: "Enterprise SSO (OIDC)",
        status: "live",
        flag: "SSO_ENABLED",
        blurb:
          "PKCE flow, state/nonce replay protection, JIT user provisioning, multi-tenant IdP registry.",
        since: "2.1.0",
      },
      {
        name: "SCIM 2.0 provisioning",
        status: "live",
        flag: "SCIM_ENABLED",
        blurb:
          "Token-authenticated SCIM endpoints with audit events and tenant-scoped user lifecycle.",
        since: "2.1.0",
      },
    ],
  },
  {
    id: "reliability",
    label: "Reliability & Throttling",
    description:
      "Rate limits, circuit breakers, idempotency, kill switches, async workers.",
    features: [
      {
        name: "Redis token-bucket rate limiting",
        status: "live",
        flag: "RATE_LIMIT_ENABLED",
        blurb:
          "Per-key + per-tenant dual enforcement with stable 429 schema and retry hints.",
        since: "0.9.0",
      },
      {
        name: "Idempotency keys (write endpoints)",
        status: "live",
        flag: "IDEMPOTENCY_ENABLED",
        blurb:
          "Conflict detection on write paths; write-ahead Idempotency-Key contract.",
        since: "1.3.0",
      },
      {
        name: "Async document ingestion (ARQ)",
        status: "live",
        flag: "INGEST_EXECUTION_MODE",
        blurb:
          "Redis-backed ARQ worker; 202 Accepted with status tracking and failure reasons.",
        since: "0.6.0",
      },
      {
        name: "Circuit breakers (external calls)",
        status: "live",
        flag: "CB_FAILURE_THRESHOLD",
        blurb:
          "Threshold-based breakers around LLM/retrieval providers with bulkheads and retries.",
        since: "1.5.0",
      },
      {
        name: "Kill switches (per feature)",
        status: "live",
        flag: "KILL_RUN, KILL_INGEST, …",
        kill: "kill.notifications, kill.run, kill.ingest",
        blurb:
          "Per-feature kill switches; rollout/canary controls; maintenance gates above RBAC.",
        since: "1.5.0",
      },
    ],
  },
  {
    id: "cost-sla",
    label: "Cost Governance & SLA",
    description:
      "Per-tenant budgets, chargeback, SLA enforcement, adaptive autoscaling.",
    features: [
      {
        name: "Cost governance + chargeback",
        status: "live",
        flag: "COST_GOVERNANCE_ENABLED",
        blurb:
          "Pricing catalog, tenant budgets with warn/block/degrade, spend analytics + chargeback reports.",
        since: "2.4.0",
      },
      {
        name: "SLA engine + load shedding",
        status: "live",
        flag: "SLA_ENGINE_ENABLED",
        blurb:
          "Tenant-scoped SLA policies with warn/degrade/shed enforcement on /v1/run and ingestion.",
        since: "2.5.0",
      },
      {
        name: "Autoscaling recommendations",
        status: "live",
        flag: "AUTOSCALING_ENABLED",
        blurb:
          "Adaptive autoscaling profiles + recommendation actions feeding the operability evaluator.",
        since: "2.5.0",
      },
    ],
  },
  {
    id: "crypto-backups",
    label: "Crypto & Backups",
    description:
      "Envelope encryption, KMS-rotated keys, signed encrypted backups.",
    features: [
      {
        name: "Envelope encryption (AES-256-GCM)",
        status: "live",
        flag: "CRYPTO_ENABLED",
        blurb:
          "Tenant key registry + encrypted blob store; pluggable KMS error contracts.",
        since: "1.9.0",
      },
      {
        name: "Key rotation + KMS",
        status: "live",
        flag: "CRYPTO_PROVIDER",
        blurb:
          "Resumable re-encryption jobs with telemetry; admin keyring lifecycle endpoints.",
        since: "1.9.0",
      },
      {
        name: "Encrypted + signed backups",
        status: "live",
        flag: "BACKUP_ENABLED",
        blurb:
          "Signed manifests, retention pruning, drill reporting; DR readiness ops endpoints.",
        since: "1.6.0",
      },
      {
        name: "Multi-region failover",
        status: "live",
        flag: "FAILOVER_ENABLED",
        blurb:
          "Region status, readiness arbitration, token-gated promotion + write-freeze.",
        since: "1.7.0",
      },
    ],
  },
  {
    id: "compliance",
    label: "Compliance & Governance",
    description:
      "SOC 2 controls, evidence bundles, DSAR, retention, audit log.",
    features: [
      {
        name: "SOC 2 compliance automation",
        status: "live",
        flag: "COMPLIANCE_ENABLED",
        blurb:
          "SOC 2 control catalog + continuous evaluation engine + scheduling tasks.",
        since: "2.0.0",
      },
      {
        name: "Evidence bundle generation",
        status: "live",
        blurb:
          "Persisted evidence under var/evidence with signing, verification, and retention pruning.",
        since: "2.0.0",
      },
      {
        name: "DSAR / data governance",
        status: "live",
        flag: "GOVERNANCE_POLICY_ENGINE_ENABLED",
        blurb:
          "Export/delete/anonymize APIs, retention pipeline with legal hold supersession.",
        since: "1.8.0",
      },
      {
        name: "Audit log (tamper-evident)",
        status: "live",
        flag: "always on",
        blurb:
          "Central audit service across auth, mutation, and ops paths with metadata redaction.",
        since: "0.8.0",
      },
    ],
  },
  {
    id: "observability",
    label: "Observability & Operability",
    description:
      "Metrics, alerts, incidents, operability evaluator, ops endpoints.",
    features: [
      {
        name: "Prometheus metrics (/v1/metrics)",
        status: "live",
        flag: "always on",
        blurb:
          "Standard Prom format with workload counters, latency histograms, and queue depths.",
      },
      {
        name: "Operability alerts + incidents",
        status: "live",
        flag: "ALERTING_ENABLED",
        blurb:
          "Alert rules registry, deterministic evaluation APIs, incident automation lifecycle.",
        since: "2.8.0",
      },
      {
        name: "Operability evaluator worker",
        status: "live",
        blurb:
          "Background evaluator with distributed locking + heartbeat reporting and ops summaries.",
        since: "2.8.1",
      },
      {
        name: "Notification delivery (ARQ + DLQ)",
        status: "live",
        kill: "kill.notifications",
        blurb:
          "ARQ-backed worker with HMAC signatures, dedupe, DLQ persistence, and admin replay.",
        since: "2.8.x",
      },
    ],
  },
  {
    id: "developer-experience",
    label: "Developer Experience",
    description:
      "SDKs, BFF endpoints, idempotency, versioned envelopes, OpenAPI.",
    features: [
      {
        name: "Python + TypeScript SDKs",
        status: "live",
        flag: "make sdk-generate",
        blurb:
          "Generated from OpenAPI; `make sdk-generate` regenerates with examples.",
        since: "1.3.0",
      },
      {
        name: "BFF endpoints (/v1/ui/*)",
        status: "live",
        flag: "always on",
        blurb:
          "Bootstrap, dashboard, documents, activity, actions — built for the UI without exposing internals.",
        since: "1.4.0",
      },
      {
        name: "Versioned API + envelope contracts",
        status: "live",
        blurb:
          "/v1 routes with success/error envelopes, deprecation headers on legacy aliases (sunset 2026-05-10).",
        since: "1.3.0",
      },
    ],
  },
];

/** Total feature count across all categories. */
export const FEATURE_TOTAL = FEATURE_CATEGORIES.reduce(
  (sum, c) => sum + c.features.length,
  0,
);
