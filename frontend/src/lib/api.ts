// Typed wrappers around NexusRAG BFF endpoints.
// All calls go through the Next.js rewrite proxy at /api/* → /v1/*.

const API_KEY =
  typeof window !== "undefined"
    ? process.env.NEXT_PUBLIC_API_KEY ?? ""
    : "";

function headers(): HeadersInit {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${API_KEY}`,
  };
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { ...headers(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text}`);
  }
  const json = await res.json();
  // Unwrap the standard success envelope { data: ..., meta: ... }
  return ("data" in json ? json.data : json) as T;
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface BootstrapData {
  principal: { tenant_id: string; role: string; api_key_id: string; subject_id: string };
  plan: { plan_id: string; plan_name: string | null };
  entitlements: Record<string, { enabled: boolean }>;
  quota_snapshot: {
    day: { limit: number | null; used: number; remaining: number | null };
    month: { limit: number | null; used: number; remaining: number | null };
    soft_cap_reached: boolean;
    hard_cap_mode: string;
  };
  feature_flags: Record<string, boolean>;
  server_time: string;
  api: Record<string, string>;
}

export interface StatCard {
  id: string;
  title: string;
  value: string;
  subtitle?: string;
}

export interface DashboardAlert {
  id: string;
  message: string;
  severity: string;
}

export interface DashboardData {
  cards: StatCard[];
  charts: Record<string, { id: string; points: unknown[] }>;
  alerts: DashboardAlert[];
}

export interface DocumentRow {
  id: string;
  filename: string;
  status: string;
  corpus_id: string;
  content_type: string;
  created_at: string;
  updated_at: string;
  last_reindexed_at: string | null;
}

export interface FacetValue { value: string; count: number }

export interface PagedResponse<T> {
  items: T[];
  page: { next_cursor: string | null; has_more: boolean };
  facets: Record<string, FacetValue[]>;
}

export interface ActivityItem {
  id: number;
  occurred_at: string;
  event_type: string;
  outcome: string;
  actor_type: string | null;
  actor_id: string | null;
  resource_type: string | null;
  resource_id: string | null;
  summary: string;
}

export interface ReindexResponse {
  action_id: string;
  status: string;
  accepted_at: string;
  optimistic: { entity: string; id: string; patch: Record<string, string> };
  poll_url: string;
}

// ── Fetchers ──────────────────────────────────────────────────────────────────

export function fetchBootstrap(): Promise<BootstrapData> {
  return apiFetch<BootstrapData>("/ui/bootstrap");
}

export function fetchDashboard(): Promise<DashboardData> {
  return apiFetch<DashboardData>("/ui/dashboard/summary");
}

export function fetchDocuments(params: {
  q?: string;
  status?: string;
  cursor?: string;
  limit?: number;
}): Promise<PagedResponse<DocumentRow>> {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.status) sp.set("status", params.status);
  if (params.cursor) sp.set("cursor", params.cursor);
  sp.set("limit", String(params.limit ?? 20));
  return apiFetch<PagedResponse<DocumentRow>>(`/ui/documents?${sp}`);
}

export function fetchActivity(params: {
  cursor?: string;
  limit?: number;
}): Promise<PagedResponse<ActivityItem>> {
  const sp = new URLSearchParams();
  if (params.cursor) sp.set("cursor", params.cursor);
  sp.set("limit", String(params.limit ?? 10));
  return apiFetch<PagedResponse<ActivityItem>>(`/ui/activity?${sp}`);
}

export function reindexDocument(documentId: string): Promise<ReindexResponse> {
  return apiFetch<ReindexResponse>("/ui/actions/reindex-document", {
    method: "POST",
    body: JSON.stringify({ document_id: documentId }),
  });
}
