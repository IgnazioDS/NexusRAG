# Operability Evaluator

## Purpose
- Keep alert evaluation and incident automation active without depending on live API traffic.

## Worker
- Service: `operability_worker`
- Entrypoint: `scripts/operability_worker.py`
- Loop interval: `OPERABILITY_EVAL_INTERVAL_S`

## Health
- Worker heartbeat key: `operability_worker_heartbeat_ts`
- `/v1/ops/health` exposes:
  - `operability_worker_heartbeat_age_s`
- `/v1/ops/operability` exposes:
  - `evaluator_heartbeat_age_s`

## Locking
- Redis lock key: `nexusrag:ops:evaluator:lock`
- TTL: `OPERABILITY_EVAL_LOCK_TTL_S`
- Invariant: one active evaluator owner at a time.

## Triage
1. Check worker logs:
   - `docker compose logs --tail=200 operability_worker`
2. Verify lock contention:
   - look for repeated `skipped_lock` cycle status in logs.
3. Verify rules and incidents:
   - `GET /v1/admin/alerts/rules`
   - `GET /v1/admin/incidents?status=open`

## Invariants
- Tenant evaluation set is derived from persisted tenant state.
- Alert and incident writes happen inside normal service transactions.
- When Redis is unavailable, evaluator heartbeats are absent and ops surfaces degrade gracefully.
