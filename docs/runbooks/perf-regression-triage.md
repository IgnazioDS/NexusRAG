# Perf Regression Triage

## Purpose

Use this runbook when `make perf-test` fails a deterministic gate.

## Workflow

1. Re-run deterministic gates to confirm reproducibility:
   - `python tests/perf/assert_perf_gates.py --deterministic --duration 90`
2. Inspect `tests/perf/reports/perf-gates-latest.json` and identify the violated gate(s).
3. Open latest scenario reports in `tests/perf/reports/*.md` and compare p95/p99 outliers by route class.
4. Check `/v1/ops/metrics` for:
   - `db_pool` saturation (`checked_out`, `overflow`)
   - `segment_latency_ms` spikes (`auth_rbac`, `retrieval`, `generation_stream`, `tts`, `persistence_*`)
   - `nexusrag_sla_*` and `nexusrag_cost_*` counters.
5. If regressions are ingestion-related, inspect `/v1/ops/ingestion` queue depth and failure reasons.
6. Apply config-only mitigations first (bulkhead and pool limits), then rerun gates.

## Common Fixes

- High `/v1/run` p95:
  - Increase `RUN_BULKHEAD_MAX_CONCURRENCY` conservatively.
  - Increase `API_DB_POOL_SIZE`/`API_DB_MAX_OVERFLOW` if pool saturation is confirmed.
  - Reduce default `top_k` in degrade mode.
- High error rate:
  - Lower retry aggressiveness to avoid storms.
  - Verify quota/rate-limit isolation by tenant.
- High ingestion queue wait:
  - Increase worker replicas or `INGEST_BULKHEAD_MAX_CONCURRENCY`.
  - Reduce ingestion burst concurrency.

## Exit Criteria

- All deterministic perf gates pass.
- Root cause and mitigation are documented in the release notes.
