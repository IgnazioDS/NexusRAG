/**
 * NexusRAG architecture model — derived from the README "Architecture
 * Overview" diagram and the runbooks under docs/runbooks/. Used by the
 * /architecture page to render component breakdowns and the request
 * authorization pipeline.
 */

export interface ArchComponent {
  /** Stable id used for in-page anchors. */
  id: string;
  label: string;
  /** Sub-label (1-line technology hint). */
  subLabel: string;
  /** Short description for the card body. */
  description: string;
  /** Optional list of bullets — config flags, runbooks, or contract refs. */
  bullets?: string[];
}

export interface ArchLayer {
  id: string;
  label: string;
  description: string;
  components: ArchComponent[];
}

export const LAYERS: ArchLayer[] = [
  {
    id: "edge",
    label: "Edge & Auth",
    description:
      "Every request passes through a layered gate before any retrieval or generation work happens.",
    components: [
      {
        id: "rate-limit",
        label: "Rate limit",
        subLabel: "Redis · token-bucket",
        description:
          "Per-key + per-tenant dual enforcement with stable 429 schema, retry hints, and audit events for throttling and degraded mode.",
        bullets: [
          "Flag: RATE_LIMIT_ENABLED",
          "Per route-class policies",
          "Stable 429 schema with throttling headers",
        ],
      },
      {
        id: "auth",
        label: "Auth",
        subLabel: "API key + SSO/SCIM",
        description:
          "Hashed API key storage; OIDC SSO with PKCE + state/nonce replay protection; SCIM 2.0 token-authenticated provisioning.",
        bullets: [
          "Flag: AUTH_ENABLED, SSO_ENABLED, SCIM_ENABLED",
          "Optional dev bypass via AUTH_DEV_BYPASS",
          "Inactive key denial: AUTH_INACTIVE_KEY",
        ],
      },
      {
        id: "rbac",
        label: "RBAC",
        subLabel: "reader / editor / admin",
        description:
          "Role gate on every protected endpoint. Admin role does not bypass document ACLs unless AUTHZ_ADMIN_BYPASS_DOCUMENT_ACL=true.",
        bullets: [
          "Tenant binding from authenticated principal",
          "Role matrix in README (per endpoint)",
        ],
      },
      {
        id: "abac",
        label: "ABAC",
        subLabel: "policy engine",
        description:
          "Priority-aware deny-first / allow-then policies with simulation API and DSL conditions (eq, time_between, var).",
        bullets: [
          "Flag: AUTHZ_ABAC_ENABLED",
          "Wildcards gated by AUTHZ_ALLOW_WILDCARDS",
          "Simulation endpoint: POST /v1/admin/authz/policies/{id}/simulate",
        ],
      },
      {
        id: "doc-acl",
        label: "Doc ACL",
        subLabel: "creator-owner default",
        description:
          "Per-document grants (read / write / admin) with expiring grants ignored. Default-deny posture configurable.",
        bullets: [
          "Flag: AUTHZ_DEFAULT_DENY",
          "Document creators receive owner ACL on create",
          "Grant API: POST /v1/admin/authz/documents/{id}/permissions",
        ],
      },
    ],
  },
  {
    id: "agent",
    label: "Agent Runtime",
    description:
      "Stateful LangGraph agent serving the public /v1/run endpoint with progressive SSE streaming.",
    components: [
      {
        id: "langgraph",
        label: "LangGraph agent",
        subLabel: "/v1/run · SSE",
        description:
          "State graph orchestrates retrieval → generation → optional TTS. Request_id tracing on every event; reconnect-safe sequence numbers.",
        bullets: [
          "Streaming progressive tokens with minimal buffering",
          "Quality guardrails emit SSE events",
          "Optional /audio.ready events when TTS_PROVIDER=openai",
        ],
      },
      {
        id: "router",
        label: "Retrieval router",
        subLabel: "per-corpus provider",
        description:
          "Each corpus picks its retrieval provider in corpora.provider_config_json. Empty config normalizes to local pgvector.",
        bullets: [
          "Provider: local_pgvector | aws_bedrock_kb | gcp_vertex",
          "Default top_k_default: 5",
          "Cloud creds at runtime; tests run mock-only",
        ],
      },
      {
        id: "llm",
        label: "Generator",
        subLabel: "Gemini · Vertex AI",
        description:
          "Pluggable LLM provider with deterministic fake-LLM path for tests. Timeout + cancellation handling for streaming paths.",
        bullets: [
          "Flag: LLM_PROVIDER",
          "Deterministic fake provider for hermetic tests",
        ],
      },
    ],
  },
  {
    id: "retrieval",
    label: "Retrieval Backends",
    description:
      "Three production backends, each isolated behind the router with mock-tested adapters.",
    components: [
      {
        id: "pgvector",
        label: "PostgreSQL + pgvector",
        subLabel: "local default",
        description:
          "Cosine retrieval with similarity scoring, deterministic ordering, embedding-dimension invariants, race-safe upserts.",
        bullets: [
          "Alembic migrations enforce pgvector extension",
          "Top-k default: 5",
        ],
      },
      {
        id: "bedrock",
        label: "AWS Bedrock KB",
        subLabel: "managed",
        description:
          "Knowledge Base id + region selectable per corpus. Bedrock adapter mock-tested in CI without live creds.",
        bullets: [
          "Provider: aws_bedrock_kb",
          "Per-corpus knowledge_base_id + region",
        ],
      },
      {
        id: "vertex",
        label: "GCP Vertex AI Search",
        subLabel: "Discovery Engine",
        description:
          "Discovery Engine datastores wired through the same router. Vertex adapter mock-tested with config-error mapping.",
        bullets: [
          "Provider: gcp_vertex",
          "Per-corpus project + location + resource_id",
        ],
      },
    ],
  },
  {
    id: "infra",
    label: "Infrastructure",
    description:
      "Stateful and durable building blocks shared across the platform.",
    components: [
      {
        id: "postgres",
        label: "PostgreSQL",
        subLabel: "system of record",
        description:
          "Tenants, corpora, documents, chunks, audit log, compliance evidence, encrypted blobs, retention runs — all here. Alembic-migrated.",
        bullets: [
          "audit_events table for tamper-evident audit",
          "var/evidence persisted artifact paths",
          "Tenant guard + RLS posture checks",
        ],
      },
      {
        id: "redis",
        label: "Redis",
        subLabel: "rate limits · idempotency · ARQ",
        description:
          "Token-bucket rate limit state, idempotency conflict detection, and ARQ job queues for async ingestion + notifications.",
        bullets: [
          "Idempotency-Key contract on writes",
          "ARQ workers: ingestion + notification delivery",
        ],
      },
      {
        id: "workers",
        label: "ARQ Workers",
        subLabel: "ingestion · notifications · evaluator",
        description:
          "Three durable worker pools — ingestion (chunk + embed + persist), notification delivery, operability evaluator.",
        bullets: [
          "Notification jobs/attempts as durable source of truth",
          "Evaluator with distributed locking + heartbeats",
        ],
      },
      {
        id: "kms",
        label: "KMS / Keyring",
        subLabel: "envelope encryption",
        description:
          "Tenant key registry + encrypted blob store. Pluggable KMS providers; resumable re-encryption jobs with telemetry.",
        bullets: [
          "Flag: CRYPTO_ENABLED, CRYPTO_PROVIDER",
          "Admin: /v1/admin/keyring + /v1/admin/keys",
          "KEYRING_MASTER_KEY_REQUIRED for required-only mode",
        ],
      },
    ],
  },
];

export interface PipelineStep {
  step: number;
  label: string;
  /** What this step does in 1 sentence. */
  detail: string;
  /** Outcome on failure. */
  failure: string;
}

/**
 * The decision pipeline for any document action — copied from the README
 * "Authorization Model" section to make the order explicit on the dashboard.
 */
export const AUTHZ_PIPELINE: PipelineStep[] = [
  {
    step: 1,
    label: "Tenant boundary",
    detail:
      "Non-bypassable tenant scoping. The principal's tenant_id is checked against every resource's tenant_id.",
    failure: "TENANT_MISMATCH — request rejected before any policy runs.",
  },
  {
    step: 2,
    label: "Kill switches / maintenance gates",
    detail:
      "Per-feature kill switches and maintenance windows take precedence over RBAC and ABAC.",
    failure: "FEATURE_DISABLED or MAINTENANCE_MODE — short-circuit denial.",
  },
  {
    step: 3,
    label: "RBAC role gate",
    detail:
      "Endpoint-level role check. The role matrix in README pins minimum role per route.",
    failure: "ROLE_INSUFFICIENT — denied with the required role surfaced.",
  },
  {
    step: 4,
    label: "Document ACL evaluation",
    detail:
      "Explicit grants (read / write / admin) for the principal. Expired grants are ignored. Owner = automatic admin.",
    failure: "ACL_DENIED — no matching grant or only expired grants found.",
  },
  {
    step: 5,
    label: "ABAC policy evaluation",
    detail:
      "Deny-first then allow-then. Higher priority wins. Conditions evaluated against principal, resource labels, and request context.",
    failure: "POLICY_DENIED — surfaced with the matching policy name.",
  },
  {
    step: 6,
    label: "Default deny",
    detail:
      "If no allow policy matched, the configurable default is applied (default deny in production).",
    failure: "DEFAULT_DENY — terminal step; flag controls behavior.",
  },
];
