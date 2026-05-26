from __future__ import annotations

import pytest
from sqlalchemy import delete

from nexusrag.benchmark import runner
from nexusrag.domain.models import Chunk, Corpus
from nexusrag.persistence.db import SessionLocal


async def _cleanup() -> None:
    # The runner commits real corpora/chunks; remove the namespaced benchmark
    # rows so this test leaves no residue for others (the suite commits + cleans
    # up explicitly rather than relying on transaction rollback).
    async with SessionLocal() as session:
        for corpus in ("rag", "pgvector", "http"):
            cid = runner._corpus_id(corpus)
            await session.execute(delete(Chunk).where(Chunk.corpus_id == cid))
            await session.execute(delete(Corpus).where(Corpus.id == cid))
        await session.commit()


@pytest.mark.asyncio
async def test_runner_indexes_retrieves_and_scores_end_to_end() -> None:
    docs, cases = runner.load_fixture()
    assert docs, "fixture corpus.jsonl should not be empty"
    assert cases, "fixture cases.jsonl should not be empty"

    await _cleanup()
    try:
        async with SessionLocal() as session:
            await runner.index_fixture(session, docs)
            answerable, adversarial, per_corpus = await runner.run_cases(session, cases)
        metrics = runner.aggregate(answerable, adversarial, per_corpus)
    finally:
        await _cleanup()

    # Structure + ranges only. The fake (lexical) embedding makes specific recall
    # values meaningless, so we assert the harness runs end-to-end and produces
    # well-formed metrics — proving a quality threshold is the semantic run's job.
    assert answerable, "fixture should contain answerable cases"
    assert metrics["retrieval"]["cases"] == len(answerable)
    for key in (
        "recall_at_1",
        "recall_at_3",
        "recall_at_5",
        "precision_at_3",
        "ndcg_at_10",
        "mean_top_score",
    ):
        assert 0.0 <= metrics["retrieval"][key] <= 1.0, f"{key} out of range"

    # Adversarial cases (no relevant doc) are scored separately, never folded in.
    assert metrics["adversarial"]["cases"] >= 1
    assert 0.0 <= metrics["adversarial"]["mean_top_score"] <= 1.0

    # Per-corpus breakdown covers exactly the corpora that had answerable cases.
    assert set(metrics["per_corpus"]) == {row["corpus"] for row in answerable}


@pytest.mark.asyncio
async def test_runner_write_artifact_carries_previous(tmp_path, monkeypatch) -> None:
    # write_artifact should roll the prior run into previous_run. Point the module
    # artifact path at a tmp file so the test never touches the committed one.
    artifact = tmp_path / "latest_run.json"
    monkeypatch.setattr(runner, "_ARTIFACT", artifact)

    first = runner.write_artifact({"retrieval": {"recall_at_5": 0.4}}, case_count=18, provider="fake")
    assert first["status"] == "ok"
    assert first["latest"]["embedding_provider"] == "fake"
    assert first["previous_run"] is None

    second = runner.write_artifact({"retrieval": {"recall_at_5": 0.9}}, case_count=18, provider="openai")
    assert second["latest"]["metrics"]["retrieval"]["recall_at_5"] == 0.9
    assert second["latest"]["embedding_provider"] == "openai"
    assert second["previous_run"]["metrics"]["retrieval"]["recall_at_5"] == 0.4
