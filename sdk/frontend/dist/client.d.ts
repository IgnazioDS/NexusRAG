import { UiActionResponse, UiActivityData, UiBootstrapData, UiDashboardData, UiDocumentsData } from "./types";
export declare class UiApiError extends Error {
    code: string;
    status: number;
    details?: Record<string, unknown>;
    constructor(message: string, code: string, status: number, details?: Record<string, unknown>);
}
export interface UiClientOptions {
    baseUrl: string;
    apiKey: string;
    fetcher?: typeof fetch;
}
export declare class UiClient {
    private baseUrl;
    private apiKey;
    private fetcher;
    constructor(options: UiClientOptions);
    private request;
    bootstrap(): Promise<UiBootstrapData>;
    dashboardSummary(windowDays?: number): Promise<UiDashboardData>;
    listDocuments(query: string): Promise<UiDocumentsData>;
    listActivity(query: string): Promise<UiActivityData>;
    reindexDocument(documentId: string, idempotencyKey?: string): Promise<UiActionResponse>;
}
