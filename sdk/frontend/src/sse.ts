import { RunStreamEvent } from "./types";

export interface RunStreamOptions {
  baseUrl: string;
  apiKey: string;
  body: Record<string, unknown>;
  onEvent: (event: RunStreamEvent) => void;
  onError?: (error: Error) => void;
  onDone?: () => void;
  heartbeatTimeoutMs?: number;
  maxRetries?: number;
  initialRetryMs?: number;
}

export interface RunStreamHandle {
  close: () => void;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function connectRunStream(options: RunStreamOptions): RunStreamHandle {
  const {
    baseUrl,
    apiKey,
    body,
    onEvent,
    onError,
    onDone,
    heartbeatTimeoutMs = 20000,
    maxRetries = 3,
    initialRetryMs = 500,
  } = options;

  let aborted = false;
  let lastSeq: number | null = null;
  let lastEventAt = Date.now();
  let attempt = 0;

  const controller = new AbortController();

  const run = async () => {
    while (!aborted && attempt <= maxRetries) {
      attempt += 1;
      try {
        const headers: Record<string, string> = {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        };
        if (lastSeq !== null) {
          headers["Last-Event-ID"] = String(lastSeq);
        }

        const response = await fetch(`${baseUrl.replace(/\\/$/, "")}/v1/run`, {
          method: "POST",
          headers,
          body: JSON.stringify(body),
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(`Run stream failed with status ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let currentEvent = "message";

        const heartbeatCheck = async () => {
          while (!aborted) {
            if (Date.now() - lastEventAt > heartbeatTimeoutMs) {
              reader.cancel().catch(() => undefined);
              return;
            }
            await sleep(heartbeatTimeoutMs / 2);
          }
        };

        heartbeatCheck().catch(() => undefined);

        while (!aborted) {
          const { value, done } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf("\n")) !== -1) {
            const line = buffer.slice(0, idx).trimEnd();
            buffer = buffer.slice(idx + 1);
            if (!line) {
              continue;
            }
            if (line.startsWith("event:")) {
              currentEvent = line.slice(6).trim();
              continue;
            }
            if (line.startsWith("data:")) {
              const raw = line.slice(5).trim();
              const payload = JSON.parse(raw);
              lastEventAt = Date.now();
              if (typeof payload.seq === "number") {
                lastSeq = payload.seq;
              }
              if (payload.type === "resume.unsupported") {
                onEvent({ event: currentEvent, data: payload });
                onDone?.();
                return;
              }
              onEvent({ event: currentEvent, data: payload });
              if (payload.type === "done") {
                onDone?.();
                return;
              }
            }
          }
        }
      } catch (err) {
        if (aborted) {
          return;
        }
        onError?.(err as Error);
      }

      if (attempt <= maxRetries) {
        const delay = initialRetryMs * Math.pow(2, attempt - 1);
        await sleep(delay);
      }
    }
  };

  run().catch((err) => onError?.(err as Error));

  return {
    close: () => {
      aborted = true;
      controller.abort();
    },
  };
}
