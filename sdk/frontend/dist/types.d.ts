export interface UiResponseMeta {
    request_id: string;
    api_version: string;
}
export interface UiSuccessEnvelope<T> {
    data: T;
    meta: UiResponseMeta;
}
export interface UiErrorDetail {
    code: string;
    message: string;
    details?: Record<string, unknown>;
}
export interface UiErrorEnvelope {
    error: UiErrorDetail;
    meta: UiResponseMeta;
}
export interface UiPrincipal {
    tenant_id: string;
    role: string;
    api_key_id: string;
    subject_id: string;
}
export interface UiPlan {
    plan_id: string;
    plan_name?: string | null;
}
export interface UiEntitlement {
    enabled: boolean;
    config_json?: Record<string, unknown> | null;
}
export interface UiQuotaSnapshot {
    day: Record<string, unknown>;
    month: Record<string, unknown>;
    soft_cap_reached: boolean;
    hard_cap_mode: string;
}
export interface UiBootstrapData {
    principal: UiPrincipal;
    plan: UiPlan;
    entitlements: Record<string, UiEntitlement>;
    quota_snapshot: UiQuotaSnapshot;
    feature_flags: Record<string, boolean>;
    server_time: string;
    api: {
        version: string;
    };
}
export interface UiCard {
    id: string;
    title: string;
    value: string;
    subtitle?: string | null;
}
export interface UiChart {
    id: string;
    points: Array<{
        ts: string;
        value: number;
    }>;
}
export interface UiAlert {
    id: string;
    message: string;
    severity: "info" | "warning" | "error";
}
export interface UiDashboardData {
    cards: UiCard[];
    charts: Record<string, UiChart>;
    alerts: UiAlert[];
}
export interface UiPage {
    next_cursor?: string | null;
    has_more: boolean;
}
export interface UiFacetValue {
    value: string;
    count: number;
}
export interface UiDocumentRow {
    id: string;
    filename: string;
    status: string;
    corpus_id: string;
    content_type: string;
    created_at: string;
    updated_at: string;
    last_reindexed_at?: string | null;
}
export interface UiDocumentsData {
    items: UiDocumentRow[];
    page: UiPage;
    facets: Record<string, UiFacetValue[]>;
}
export interface UiActivityItem {
    id: number;
    occurred_at: string;
    event_type: string;
    outcome: string;
    actor_type?: string | null;
    actor_id?: string | null;
    resource_type?: string | null;
    resource_id?: string | null;
    summary: string;
}
export interface UiActivityData {
    items: UiActivityItem[];
    page: UiPage;
    facets: Record<string, UiFacetValue[]>;
}
export interface UiActionOptimisticPatch {
    entity: string;
    id: string;
    patch: Record<string, unknown>;
}
export interface UiActionResponse {
    action_id: string;
    status: string;
    accepted_at: string;
    optimistic: UiActionOptimisticPatch;
    poll_url: string;
}
export interface RunStreamEvent<T = any> {
    event: string;
    data: T;
}
