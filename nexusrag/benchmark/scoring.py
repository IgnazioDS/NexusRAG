"""Pure scoring functions for the NexusRAG benchmark.

No I/O, no external deps — just math over ranked id lists and strings, so it
is unit-testable with hand-computed values and importable anywhere. Every
number the benchmark publishes flows through here from real retrieval /
generation output; nothing is seeded.

Retrieval relevance is matched on document ids (retrieval results expose
`source = "document://{doc_id}"`, so callers extract the doc_id). Generation
quality uses token-overlap F1, a deterministic proxy that needs no LLM judge.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Fraction of the relevant set found within the top-k retrieved ids."""
    rel = set(relevant)
    if not rel:
        return 0.0
    topk = set(retrieved[:k])
    hits = sum(1 for r in rel if r in topk)
    return hits / len(rel)


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Fraction of the top-k retrieved ids that are relevant."""
    if k <= 0:
        return 0.0
    topk = list(retrieved[:k])
    if not topk:
        return 0.0
    rel = set(relevant)
    hits = sum(1 for d in topk if d in rel)
    return hits / len(topk)


def ndcg_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Binary-relevance nDCG@k (ideal ranking = all relevant docs first)."""
    rel = set(relevant)
    if not rel:
        return 0.0
    dcg = 0.0
    for i, doc in enumerate(retrieved[:k]):
        if doc in rel:
            dcg += 1.0 / math.log2(i + 2)  # 0-based rank i -> position i+1
    ideal_hits = min(len(rel), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def token_overlap_f1(prediction: str, reference: str) -> float:
    """Token-overlap F1 between a generated answer and a reference answer.

    Deterministic generation-quality proxy (no LLM judge). Returns 0.0 when
    either side has no tokens. Unanswerable cases (empty reference) should be
    scored as abstention by the caller, not routed through here.
    """
    pred = _TOKEN_RE.findall(prediction.lower())
    ref = _TOKEN_RE.findall(reference.lower())
    if not pred or not ref:
        return 0.0
    pred_counts = Counter(pred)
    ref_counts = Counter(ref)
    overlap = sum((pred_counts & ref_counts).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(ref)
    return 2 * precision * recall / (precision + recall)


def percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile, pct in [0, 100]. Empty input -> 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(ordered[lo])
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac
