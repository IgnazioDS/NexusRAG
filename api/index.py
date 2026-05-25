"""Vercel serverless entry point for the NexusRAG FastAPI application.

Vercel's Python runtime discovers this file and routes all incoming
requests through the FastAPI ASGI app via the ``vercel.json`` rewrite
rules.  No database or Redis connection is established at import time;
connections are created lazily on the first request that needs them.
"""

import time as _time

_cold_start_began = _time.perf_counter()
from nexusrag.apps.api.main import app  # noqa: E402,F401

# Emit import cost to Vercel runtime logs (COLD_START_IMPORT_MS=...) so the
# import-time cold-start can be measured directly from production logs.
print(f"COLD_START_IMPORT_MS={(_time.perf_counter() - _cold_start_began) * 1000:.0f}")
