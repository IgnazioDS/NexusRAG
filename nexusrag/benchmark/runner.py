"""Public retrieval benchmark runner for NexusRAG.

Indexes the committed `examples/benchmark-v1` fixture into an isolated synthetic
tenant, runs live retrieval for every labeled query, scores recall / precision /
nDCG against the ground-truth `relevant_doc_ids`, and writes a committed JSON
artifact that `/api/benchmark-latest` serves.

Honesty contract: every number is computed here, from the fixed committed
fixture against the same retrieval path the product uses. Nothing is seeded. The
artifact records `embedding_provider`, so a lexical `fake` run is never read as
semantic. Adversarial cases (no relevant doc) are scored separately as a
false-confidence signal, not folded into recall/precision.

Run:  python -m nexusrag.benchmark.runner
A real semantic run sets EMBEDDING_PROVIDER=openai (or vertex) with the matching
key; tests run it with the default fake provider and an ephemeral pgvector DB.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.benchmark import scoring
from nexusrag.core.config import EMBED_DIM, get_settings
from nexusrag.domain.models import Chunk, Corpus
from nexusrag.ingestion.embeddings import embed_text
from nexusrag.persistence.db import SessionLocal
from nexusrag.providers.retrieval.router import RetrievalRouter

FIXTURE_VERSION = "benchmark-v1"
BENCHMARK_TENANT = "benchmark"
TOP_K = 10

# Fixture lives at <repo>/examples/benchmark-v1; runner is nexusrag/benchmark/runner.py.
_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "examples" / FIXTURE_VERSION
# Published artifact ships inside the package so the lambda reads it from disk.
_ARTIFACT = Path(__file__).resolve().parent / "data" / "latest_run.json"


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_fixture() -> tuple[list[dict], list[dict]]:
    return _load_jsonl(_FIXTURE_DIR / "corpus.jsonl"), _load_jsonl(_FIXTURE_DIR / "cases.jsonl")


def _corpus_id(corpus: str) -> str:
    return f"{FIXTURE_VERSION}-{corpus}"


async def _allow_entitlement(**_kwargs: object) -> None:
    # The benchmark tenant is synthetic and has no plan row, so bypass entitlement
    # gating here exactly as the retrieval-router unit tests do. This is internal
    # tooling, not a tenant request.
    return None


async def index_fixture(session: AsyncSession, docs: list[dict]) -> None:
    """Create one isolated corpus per fixture group and embed each doc as one chunk.

    Idempotent: re-running drops the prior benchmark chunks first, so the index
    always reflects the current fixture and never accumulates stale vectors.
    """
    config = {"retrieval": {"provider": "local_pgvector", "top_k_default": TOP_K}}
    for corpus in sorted({d["corpus"] for d in docs}):
        cid = _corpus_id(corpus)
        existing = await session.get(Corpus, cid)
        if existing is None:
            session.add(
                Corpus(id=cid, tenant_id=BENCHMARK_TENANT, name=f"benchmark/{corpus}", provider_config_json=config)
            )
        else:
            existing.tenant_id = BENCHMARK_TENANT
            existing.provider_config_json = config
        await session.execute(delete(Chunk).where(Chunk.corpus_id == cid))
    await session.flush()

    for doc in docs:
        embedding = embed_text(doc["text"])
        if len(embedding) != EMBED_DIM:
            raise ValueError(f"embedding dim {len(embedding)} != EMBED_DIM {EMBED_DIM}")
        session.add(
            Chunk(
                id=uuid4(),
                corpus_id=_corpus_id(doc["corpus"]),
                document_uri=doc["doc_id"],
                chunk_index=0,
                text=doc["text"],
                embedding=embedding,
                metadata_json={
                    "doc_id": doc["doc_id"],
                    "corpus": doc["corpus"],
                    "title": doc.get("title", ""),
                    "source_type": "benchmark",
                },
            )
        )
    await session.commit()


async def run_cases(
    session: AsyncSession, cases: list[dict]
) -> tuple[list[dict], list[dict], dict[str, list[dict]]]:
    """Retrieve for every case and score answerable vs adversarial separately."""
    router = RetrievalRouter(session, entitlement_checker=_allow_entitlement)
    answerable: list[dict] = []
    adversarial: list[dict] = []
    per_corpus: dict[str, list[dict]] = {}

    for case in cases:
        results = await router.retrieve(BENCHMARK_TENANT, _corpus_id(case["corpus"]), case["query"], TOP_K)
        retrieved = [r["source"] for r in results]
        top_score = float(results[0]["score"]) if results else 0.0
        relevant = case.get("relevant_doc_ids") or []
        if not relevant:
            # No ground-truth doc: a closed-corpus retriever always returns its
            # nearest neighbours, so the meaningful signal is how confident it is
            # on an out-of-corpus query (lower top_score = better).
            adversarial.append({"id": case["id"], "top_score": top_score})
            continue
        row = {
            "id": case["id"],
            "corpus": case["corpus"],
            "recall_at_1": scoring.recall_at_k(retrieved, relevant, 1),
            "recall_at_3": scoring.recall_at_k(retrieved, relevant, 3),
            "recall_at_5": scoring.recall_at_k(retrieved, relevant, 5),
            "precision_at_3": scoring.precision_at_k(retrieved, relevant, 3),
            "ndcg_at_10": scoring.ndcg_at_k(retrieved, relevant, 10),
            "top_score": top_score,
        }
        answerable.append(row)
        per_corpus.setdefault(case["corpus"], []).append(row)

    return answerable, adversarial, per_corpus


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _agg(rows: list[dict]) -> dict:
    return {
        "cases": len(rows),
        "recall_at_1": _mean([r["recall_at_1"] for r in rows]),
        "recall_at_3": _mean([r["recall_at_3"] for r in rows]),
        "recall_at_5": _mean([r["recall_at_5"] for r in rows]),
        "precision_at_3": _mean([r["precision_at_3"] for r in rows]),
        "ndcg_at_10": _mean([r["ndcg_at_10"] for r in rows]),
        "mean_top_score": _mean([r["top_score"] for r in rows]),
    }


def aggregate(answerable: list[dict], adversarial: list[dict], per_corpus: dict[str, list[dict]]) -> dict:
    return {
        "retrieval": _agg(answerable),
        "adversarial": {
            "cases": len(adversarial),
            "mean_top_score": _mean([a["top_score"] for a in adversarial]),
        },
        "per_corpus": {corpus: _agg(rows) for corpus, rows in sorted(per_corpus.items())},
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_artifact(metrics: dict, case_count: int, provider: str) -> dict:
    """Write the committed run artifact, carrying the prior run as previous_run."""
    previous = None
    if _ARTIFACT.exists():
        try:
            previous = json.loads(_ARTIFACT.read_text(encoding="utf-8")).get("latest")
        except (json.JSONDecodeError, OSError):
            previous = None
    latest = {
        "run_id": str(uuid4()),
        "fixture_version": FIXTURE_VERSION,
        "embedding_provider": provider,
        "generated_at": _now_iso(),
        "case_count": case_count,
        "metrics": metrics,
    }
    payload = {
        "system": "nexusrag",
        "schema_version": 1,
        "status": "ok",
        "latest": latest,
        "previous_run": previous,
        "generated_at": _now_iso(),
    }
    _ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    _ARTIFACT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


async def _run() -> int:
    provider = getattr(get_settings(), "embedding_provider", "fake")
    docs, cases = load_fixture()
    async with SessionLocal() as session:
        await index_fixture(session, docs)
        answerable, adversarial, per_corpus = await run_cases(session, cases)
    metrics = aggregate(answerable, adversarial, per_corpus)
    payload = write_artifact(metrics, len(answerable) + len(adversarial), provider)
    print(json.dumps(payload["latest"], indent=2))
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - surface any setup/DB/provider error
        print(f"benchmark runner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
