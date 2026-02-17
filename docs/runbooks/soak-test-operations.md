# Soak Test Operations

## Purpose

Run and evaluate short and extended soak workloads before GA rollout.

## Pre-checks

- Services up: `docker compose up --build -d`
- Migrations applied: `docker compose exec api alembic upgrade head`
- Deterministic mode set when required (`PERF_FAKE_PROVIDER_MODE=true`).

## Commands

- Deterministic short soak:
  - `docker compose exec api python tests/perf/scenarios/run_mixed.py --duration 900 --deterministic`
- Full perf gates:
  - `docker compose exec api make perf-test`
- Summary report:
  - `docker compose exec api make perf-report`

## Monitoring During Soak

Poll every 1-2 minutes:

- `/v1/ops/metrics` for `segment_latency_ms`, `db_pool`, queue depth, breaker state.
- `/v1/ops/slo` for burn-rate and latency status.

## Pass Criteria

- No monotonic memory growth beyond gate threshold.
- No sustained tenant starvation in noisy-neighbor scenario.
- Error-rate and p95 gates remain within thresholds.
