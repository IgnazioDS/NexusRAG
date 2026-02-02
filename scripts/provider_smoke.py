from __future__ import annotations

import argparse
import asyncio
import sys

from nexusrag.core.errors import (
    AwsAuthError,
    AwsConfigMissingError,
    AwsRetrievalError,
    RetrievalConfigError,
    VertexRetrievalAuthError,
    VertexRetrievalConfigError,
    VertexRetrievalError,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.providers.retrieval.router import RetrievalRouter


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a retrieval-only smoke test for a configured corpus."
    )
    parser.add_argument("--tenant", required=True, help="Tenant id")
    parser.add_argument("--corpus", required=True, help="Corpus id")
    parser.add_argument("--query", required=True, help="Query string")
    parser.add_argument("--top-k", type=int, default=5, help="Number of chunks to retrieve")
    return parser


def _format_error(exc: Exception) -> tuple[int, str]:
    # Map known retrieval failures to stable, actionable messages.
    if isinstance(exc, RetrievalConfigError):
        return 2, f"RETRIEVAL_CONFIG_INVALID: {exc}"
    if isinstance(exc, AwsConfigMissingError):
        return 2, f"AWS_CONFIG_MISSING: {exc}"
    if isinstance(exc, AwsAuthError):
        return 3, f"AWS_AUTH_ERROR: {exc}"
    if isinstance(exc, AwsRetrievalError):
        return 4, f"AWS_RETRIEVAL_ERROR: {exc}"
    if isinstance(exc, VertexRetrievalConfigError):
        return 2, f"VERTEX_RETRIEVAL_CONFIG_MISSING: {exc}"
    if isinstance(exc, VertexRetrievalAuthError):
        return 3, f"VERTEX_RETRIEVAL_AUTH_ERROR: {exc}"
    if isinstance(exc, VertexRetrievalError):
        return 4, f"VERTEX_RETRIEVAL_ERROR: {exc}"
    return 1, f"UNKNOWN_ERROR: {exc}"


async def _run(args: argparse.Namespace) -> int:
    # Use the shared async session so DB/credentials config matches the API container.
    async with SessionLocal() as session:
        router = RetrievalRouter(session)
        results = await router.retrieve(args.tenant, args.corpus, args.query, args.top_k)

    for item in results:
        text = (item.get("text") or "").strip()
        snippet = (text[:120] + "...") if len(text) > 120 else text
        score = item.get("score")
        source = item.get("source")
        print(f"- score={score} source={source} text=\"{snippet}\"")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:  # noqa: BLE001 - surface actionable errors
        code, message = _format_error(exc)
        print(message, file=sys.stderr)
        return code


if __name__ == "__main__":
    raise SystemExit(main())
