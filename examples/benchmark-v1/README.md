# benchmark-v1

A small, fully committed, labeled retrieval fixture for the public NexusRAG
benchmark. Everything the benchmark scores is in this directory, so any reader
can inspect exactly what was asked and what counted as correct. Nothing is
seeded or hidden.

## Files

- `corpus.jsonl` — one JSON object per document: `{doc_id, corpus, title, text}`.
  The runner creates one isolated corpus per distinct `corpus` value, ingests
  these documents (chunk + embed + store), and retrieves only within that corpus.
- `cases.jsonl` — one labeled query per line:
  `{id, corpus, query, relevant_doc_ids, reference_answer}`.
  `relevant_doc_ids` is the ground truth used for recall / precision / nDCG.
  An empty `relevant_doc_ids` marks an **adversarial** case: the answer is not
  in the corpus, so any confidently-retrieved "relevant" doc is a false positive.

## Composition (v1)

15 documents and 18 cases across 3 corpora:

| corpus | documents | answerable queries | adversarial |
|---|---|---|---|
| `rag` | 5 | 5 | 1 |
| `pgvector` | 5 | 5 | 1 |
| `http` | 5 | 5 | 1 |

The passages are original, self-contained, factual technical descriptions; each
answerable query is grounded in exactly one passage. This is a deliberately
modest first version — the value is that it is **real and reproducible**, not
large. It is versioned (`benchmark-v1`) precisely so later versions can grow the
corpus (e.g. a SQuAD/MS MARCO subset) without breaking comparability of past runs.

## Metrics

- **Retrieval** (no LLM needed): recall@k, precision@k, nDCG@10, computed by
  matching each retrieved result's source document id against `relevant_doc_ids`.
- **Generation** (optional): token-overlap F1 of the generated answer against
  `reference_answer` — a lexical proxy, not an LLM judge.

## Honesty

Each published run records its `embedding_provider`. A `fake` run uses the
hashed bag-of-words embedding (lexical, not semantic) and its numbers must never
be read as semantic quality; a real run uses a semantic provider (`openai` /
`vertex`). The published artifact always states which.
