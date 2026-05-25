from __future__ import annotations

import math

import pytest

from nexusrag.benchmark.scoring import (
    ndcg_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    token_overlap_f1,
)


def test_recall_at_k() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = ["b", "d", "e"]
    assert recall_at_k(retrieved, relevant, 3) == pytest.approx(1 / 3)  # only b in top3
    assert recall_at_k(retrieved, relevant, 4) == pytest.approx(2 / 3)  # b + d in top4
    assert recall_at_k(retrieved, [], 3) == 0.0  # no relevant set


def test_precision_at_k() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = ["b", "d", "e"]
    assert precision_at_k(retrieved, relevant, 3) == pytest.approx(1 / 3)  # 1 of top3
    assert precision_at_k(retrieved, relevant, 2) == pytest.approx(0.5)  # b of [a,b]
    assert precision_at_k(retrieved, relevant, 0) == 0.0


def test_ndcg_at_k() -> None:
    # b@rank0 (gain 1/log2(2)=1) + d@rank2 (gain 1/log2(4)=0.5) = 1.5 dcg.
    # idcg (2 relevant ideally ranked) = 1/log2(2) + 1/log2(3).
    expected = 1.5 / (1.0 + 1.0 / math.log2(3))
    assert ndcg_at_k(["b", "a", "d"], ["b", "d"], 3) == pytest.approx(expected)
    assert ndcg_at_k(["b", "d"], ["b", "d"], 3) == pytest.approx(1.0)  # perfect
    assert ndcg_at_k(["a", "c"], ["b", "d"], 3) == 0.0  # none relevant
    assert ndcg_at_k(["a"], [], 3) == 0.0  # empty relevant


def test_token_overlap_f1() -> None:
    # overlap {the, cat} = 2; precision 2/3, recall 2/3 -> f1 2/3.
    assert token_overlap_f1("the cat sat", "the cat ran") == pytest.approx(2 / 3)
    assert token_overlap_f1("identical text", "identical text") == pytest.approx(1.0)
    assert token_overlap_f1("", "anything") == 0.0
    assert token_overlap_f1("anything", "") == 0.0
    assert token_overlap_f1("totally", "different") == 0.0


def test_percentile() -> None:
    vals = [10.0, 20.0, 30.0, 40.0]
    assert percentile(vals, 50) == pytest.approx(25.0)
    assert percentile(vals, 95) == pytest.approx(38.5)
    assert percentile([], 50) == 0.0
    assert percentile([5.0], 50) == pytest.approx(5.0)
