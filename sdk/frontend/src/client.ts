import {
  UiActionResponse,
  UiActivityData,
  UiBootstrapData,
  UiDashboardData,
  UiDocumentsData,
  UiErrorEnvelope,
  UiSuccessEnvelope,
} from "./types";

export class UiApiError extends Error {
  code: string;
  status: number;
  details?: Record<string, unknown>;

  constructor(message: string, code: string, status: number, details?: Record<string, unknown>) {
    super(message);
    this.name = "UiApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export interface UiClientOptions {
  baseUrl: string;
  apiKey: string;
  fetcher?: typeof fetch;
}

export class UiClient {
  private baseUrl: string;
  private apiKey: string;
  private fetcher: typeof fetch;

  constructor(options: UiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.apiKey = options.apiKey;
    this.fetcher = options.fetcher ?? fetch;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });

    const payload = (await response.json()) as UiSuccessEnvelope<T> | UiErrorEnvelope;
    if (!response.ok) {
      const error = payload as UiErrorEnvelope;
      throw new UiApiError(error.error.message, error.error.code, response.status, error.error.details);
    }
    return (payload as UiSuccessEnvelope<T>).data;
  }

  async bootstrap(): Promise<UiBootstrapData> {
    return this.request<UiBootstrapData>("/v1/ui/bootstrap");
  }

  async dashboardSummary(windowDays = 30): Promise<UiDashboardData> {
    return this.request<UiDashboardData>(`/v1/ui/dashboard/summary?window_days=${windowDays}`);
  }

  async listDocuments(query: string): Promise<UiDocumentsData> {
    return this.request<UiDocumentsData>(`/v1/ui/documents${query}`);
  }

  async listActivity(query: string): Promise<UiActivityData> {
    return this.request<UiActivityData>(`/v1/ui/activity${query}`);
  }

  async reindexDocument(documentId: string, idempotencyKey?: string): Promise<UiActionResponse> {
    const body = {
      document_id: documentId,
      idempotency_key: idempotencyKey,
    };
    return this.request<UiActionResponse>("/v1/ui/actions/reindex-document", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }
}
