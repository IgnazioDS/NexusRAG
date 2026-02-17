# Capacity Planning Playbook

## Purpose

Translate perf outputs into tier-level capacity and replica plans.

## Inputs

- `docs/capacity-model.md`
- `tests/perf/reports/perf-summary-latest.md`
- `tests/perf/reports/perf-gates-latest.json`

## Procedure

1. Regenerate model after tuning changes:
   - `python3 scripts/capacity_estimate.py --headroom 0.30`
2. Confirm measured p95 values are below modeled bands by tier.
3. Validate ingestion throughput assumptions against `ingest_burst` scenario output.
4. Check autoscaling recommendations align with model headroom:
   - Scale up before sustained saturation breaches.
   - Shed only after breach windows and mitigation attempts.
5. Publish planned replica baselines for standard/pro/enterprise.

## Baseline Sizing Assumptions

- Redis: single shard with persistence and reserved memory headroom.
- Postgres: primary + read replica, pool tuned via `API_DB_*` settings.
- API and worker replicas scaled independently by route pressure.

## Review Cadence

- Weekly during pre-GA.
- Per release for any runtime, retrieval, or ingestion path change.
