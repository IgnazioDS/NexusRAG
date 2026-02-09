# Incident Response Runbook

## Goals
- Restore availability quickly.
- Protect data integrity and tenant isolation.
- Capture enough context for a post-incident review.

## Triage Checklist
1) Confirm scope (single tenant vs. global).
2) Check `/v1/ops/health` for DB/Redis status.
3) Check `/v1/ops/metrics` for rate-limited/quota-exceeded/service-busy counters.
4) Check `/v1/ops/slo` for availability/burn rate.
5) Identify failing integrations (see circuit breaker states in `/v1/ops/metrics`).

## Immediate Mitigations
- Enable kill switches (admin):
  - `kill.run` for runaway generation.
  - `kill.ingest` for ingestion storms.
  - `kill.tts` for TTS outages.
  - `kill.external_retrieval` for cloud retrieval outages.
- Reduce canary percentages for unstable integrations.
- Temporarily lower `RUN_MAX_CONCURRENCY` or `INGEST_MAX_CONCURRENCY` if saturation is persistent.

## Data Integrity Actions
- Run maintenance tasks when backlog clears:
  - `prune_idempotency`
  - `prune_audit`
  - `cleanup_actions`
  - `prune_usage`

## Post-Incident
- Capture timeline, kill switch changes, breaker transitions, and recovery steps.
- Review SLO breach and error budget impact.
