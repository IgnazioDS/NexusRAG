export class UiApiError extends Error {
    constructor(message, code, status, details) {
        super(message);
        this.name = "UiApiError";
        this.code = code;
        this.status = status;
        this.details = details;
    }
}
export class UiClient {
    constructor(options) {
        this.baseUrl = options.baseUrl.replace(/\\/$ / , "");
        this.apiKey = options.apiKey;
        this.fetcher = options.fetcher ?? fetch;
    }
    async request(path, init) {
        const response = await this.fetcher(`${this.baseUrl}${path}`, {
            ...init,
            headers: {
                Authorization: `Bearer ${this.apiKey}`,
                "Content-Type": "application/json",
                ...(init?.headers ?? {}),
            },
        });
        const payload = (await response.json());
        if (!response.ok) {
            const error = payload;
            throw new UiApiError(error.error.message, error.error.code, response.status, error.error.details);
        }
        return payload.data;
    }
    async bootstrap() {
        return this.request("/v1/ui/bootstrap");
    }
    async dashboardSummary(windowDays = 30) {
        return this.request(`/v1/ui/dashboard/summary?window_days=${windowDays}`);
    }
    async listDocuments(query) {
        return this.request(`/v1/ui/documents${query}`);
    }
    async listActivity(query) {
        return this.request(`/v1/ui/activity${query}`);
    }
    async reindexDocument(documentId, idempotencyKey) {
        const body = {
            document_id: documentId,
            idempotency_key: idempotencyKey,
        };
        return this.request("/v1/ui/actions/reindex-document", {
            method: "POST",
            body: JSON.stringify(body),
        });
    }
}
