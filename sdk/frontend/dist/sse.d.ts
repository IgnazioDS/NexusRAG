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
export declare function connectRunStream(options: RunStreamOptions): RunStreamHandle;
