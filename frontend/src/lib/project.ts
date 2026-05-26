/**
 * Project metadata for NexusRAG — sourced from the repo README, CHANGELOG,
 * and feature matrix. Hardcoded as a TS module so it ships in the static
 * bundle without runtime file-system access.
 *
 * Unlike the Tier-B showcase repos, NexusRAG is a Tier-A live system. Stage
 * reflects production status; "shipped" lists what is *already running*, not
 * what is planned.
 */

export interface ProjectSpec {
  slug: string;
  name: string;
  category: string;
  track: string;
  /** "Ready to build" | "In development" | "In production" | … */
  stage: string;
  summary: string;
  problem: string;
  users: string;
  stack: string[];
  why_now: string;
  /** Production capabilities currently shipping. */
  shipped: string[];
  github_url: string;
  /** Slug returned by the system's `/api/stats` endpoint. */
  system_slug: string;
  /** Parent brand — the Eleventh Solutions site. */
  eleventh_url: string;
  /** Canonical live deploy on the eleventh.dev zone. */
  live_url: string;
  /** The full six-system fleet index on eleventh.dev. */
  fleet_url: string;
  /** Builder attribution shown in the sidebar. */
  builder: string;
}

export const PROJECT: ProjectSpec = {
  slug: "nexusrag",
  name: "NexusRAG",
  category: "AI Platform",
  track: "Production",
  stage: "Live in production",
  summary:
    "A production-grade multi-tenant RAG agent platform with streaming responses, audit logging, and pluggable retrieval across pgvector, AWS Bedrock, and GCP Vertex.",
  problem:
    "Teams shipping AI assistants need durable retrieval, tenant isolation, and audit trails — most stacks force a choice between speed-to-ship and the enterprise primitives (RBAC + ABAC, SSO/SCIM, encryption, compliance evidence) needed in regulated environments.",
  users:
    "Engineering teams building AI products, platform engineers running internal RAG, and customers needing tenant-scoped retrieval with SOC 2-grade audit logs.",
  stack: [
    "FastAPI",
    "PostgreSQL + pgvector",
    "LangGraph",
    "Redis",
    "ARQ workers",
    "Next.js 14",
    "Vercel",
    "AWS Bedrock KB",
    "GCP Vertex AI Search",
  ],
  why_now:
    "Every product wants AI features, but few teams want to build the multi-tenant guardrails — RBAC, ABAC, SSO/SCIM, envelope encryption, SOC 2 evidence, multi-region failover — from scratch. NexusRAG ships the platform; teams build on top.",
  shipped: [
    "Streaming LangGraph agent at /v1/run with SSE",
    "Multi-cloud retrieval routing (pgvector / Bedrock KB / Vertex)",
    "RBAC + ABAC + document-level ACLs with default-deny posture",
    "Enterprise SSO (OIDC) and SCIM 2.0 provisioning",
    "Envelope encryption (AES-256-GCM), KMS key rotation, encrypted backups",
    "Cost governance, SLA engine, circuit breakers, per-feature kill switches",
    "Tamper-evident audit log + SOC 2 compliance evidence automation",
    "Tier-A telemetry — workload counters, p50/p95 latency, uptime",
  ],
  github_url: "https://github.com/IgnazioDS/NexusRAG",
  system_slug: "nexusrag",
  eleventh_url: "https://eleventh.dev",
  live_url: "https://nexusrag.eleventh.dev",
  fleet_url: "https://eleventh.dev/work",
  builder: "Eleventh Solutions",
};
