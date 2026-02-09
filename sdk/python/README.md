# NexusRAG Python SDK

This SDK is generated from the OpenAPI spec under `sdk/openapi.json`.

## Generate

```bash
make sdk-generate
```

## Usage

```python
import sys
from pathlib import Path

# Ensure generated package is on the path.
sys.path.append(str(Path(__file__).resolve().parents[0] / "generated"))

from client import create_client

api = create_client(api_key="your_api_key", base_url="http://localhost:8000")
health = api.health_health_get()
print(health)
```

## Retries

The client retries 429/503 responses using `Retry-After` or `X-RateLimit-Retry-After-Ms` headers when present, with exponential backoff otherwise.
