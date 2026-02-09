# NexusRAG TypeScript SDK

This SDK is generated from the OpenAPI spec under `sdk/openapi.json`.

## Generate

```bash
make sdk-generate
```

## Usage

```ts
import { createClient } from "./client";

const api = await createClient({
  apiKey: process.env.NEXUSRAG_API_KEY!,
  basePath: "http://localhost:8000",
});

const health = await api.healthHealthGet();
console.log(health);
```

## Retries

The client retries 429/503 responses using `Retry-After` or `X-RateLimit-Retry-After-Ms` headers when present, with exponential backoff otherwise.
