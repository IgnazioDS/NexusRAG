// SSE stream parser for /v1/run.
// Uses fetch + ReadableStream instead of EventSource so we can set
// the Authorization header (EventSource API doesn't support custom headers).

export type SseEvent =
  | { type: "request.accepted"; data: { request_id: string; session_id: string } }
  | { type: "token.delta"; data: { token: string; seq: number } }
  | { type: "message.final"; data: { text: string; seq: number } }
  | { type: "audio.ready"; data: { audio_url: string; audio_id: string } }
  | { type: "audio.error"; data: { code: string; message: string } }
  | { type: "heartbeat"; data: { ts: string; request_id: string; seq: number } }
  | { type: "done"; data: Record<string, unknown> }
  | { type: "error"; data: { code: string; message: string } }
  | { type: "resume.unsupported"; data: Record<string, unknown> };

export interface RunRequest {
  session_id: string;
  corpus_id: string;
  message: string;
  top_k?: number;
  audio?: boolean;
}

export async function streamRun(
  req: RunRequest,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const apiKey = process.env.NEXT_PUBLIC_API_KEY ?? "";

  const res = await fetch("/api/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(req),
    signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Run API ${res.status}: ${text}`);
  }

  if (!res.body) throw new Error("No response body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by double newlines.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      if (!frame.trim()) continue;

      let eventType = "message";
      let dataLine = "";

      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) eventType = line.slice(7).trim();
        else if (line.startsWith("data: ")) dataLine = line.slice(6).trim();
      }

      try {
        const parsed = dataLine ? JSON.parse(dataLine) : {};
        onEvent({ type: eventType, data: parsed } as SseEvent);
      } catch {
        // Skip malformed frames.
      }
    }
  }
}
