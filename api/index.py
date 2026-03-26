"""Vercel serverless entry point for the NexusRAG FastAPI application.

Vercel's Python runtime discovers this file and routes all incoming
requests through the FastAPI ASGI app via the ``vercel.json`` rewrite
rules.  No database or Redis connection is established at import time;
connections are created lazily on the first request that needs them.
"""

from nexusrag.apps.api.main import app  # noqa: F401
