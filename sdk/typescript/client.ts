export type ClientOptions = {
  apiKey: string;
  basePath?: string;
  maxRetries?: number;
  fetchApi?: typeof fetch;
};

const defaultBasePath = "http://localhost:8000";
const defaultRetries = 2;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const retryAfterMs = (response: Response): number | null => {
  const retryAfter = response.headers.get("Retry-After");
  if (retryAfter) {
    const seconds = Number(retryAfter);
    if (!Number.isNaN(seconds)) {
      return Math.ceil(seconds * 1000);
    }
  }
  const msHeader = response.headers.get("X-RateLimit-Retry-After-Ms");
  if (msHeader) {
    const ms = Number(msHeader);
    if (!Number.isNaN(ms)) {
      return Math.ceil(ms);
    }
  }
  return null;
};

const withRetries = async (
  input: RequestInfo,
  init: RequestInit | undefined,
  retries: number,
  fetchImpl: typeof fetch,
): Promise<Response> => {
  let attempt = 0;
  while (true) {
    const response = await fetchImpl(input, init);
    if (![429, 503].includes(response.status) || attempt >= retries) {
      return response;
    }
    const delayMs = retryAfterMs(response) ?? Math.min(2000, 250 * 2 ** attempt);
    attempt += 1;
    await sleep(delayMs);
  }
};

export async function createClient(options: ClientOptions) {
  const { apiKey, basePath, maxRetries, fetchApi } = options;
  const fetchImpl = fetchApi ?? fetch;
  const { Configuration, DefaultApi } = await import("./generated");
  const config = new Configuration({
    basePath: basePath ?? defaultBasePath,
    accessToken: apiKey,
    fetchApi: (input: RequestInfo, init?: RequestInit) =>
      withRetries(input, init, maxRetries ?? defaultRetries, fetchImpl),
  });
  return new DefaultApi(config);
}
