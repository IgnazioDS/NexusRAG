# NexusRAG Frontend SDK

TypeScript-first helpers for integrating NexusRAG BFF endpoints and SSE streams into web apps.

## Install

```bash
cd sdk/frontend
npm install
npm run build
```

## Usage

```ts
import { UiClient, buildQuery, connectRunStream } from "./src";

const client = new UiClient({
  baseUrl: "http://localhost:8000",
  apiKey: process.env.NEXUSRAG_API_KEY!,
});

// Bootstrap
const bootstrap = await client.bootstrap();

// Documents table with cursor pagination
const query = buildQuery({ limit: 25, sort: "-created_at" });
const docs = await client.listDocuments(query);

// Run stream
const stream = connectRunStream({
  baseUrl: "http://localhost:8000",
  apiKey: process.env.NEXUSRAG_API_KEY!,
  body: { session_id: "sess_1", corpus_id: "corpus_1", message: "Hello", top_k: 5 },
  onEvent: ({ event, data }) => {
    if (event === "heartbeat") {
      return;
    }
    if (data.type === "token.delta") {
      console.log(data.data.delta);
    }
  },
  onDone: () => console.log("stream done"),
});
```

## Scripts

- `npm run build` - compile TypeScript to `dist/`
- `npm run test` - typecheck only
