# Controls Catalog

This catalog defines the automated controls exported by `/v1/admin/compliance/controls` and snapshots.

## Control Set

- `CC6.1` Access control enforcement (auth + ABAC enabled)
- `CC6.6` Auth failure monitoring and audit redaction
- `CC7.2` Change management evidence (changelog/release traceability)
- `CC7.3` Incident response readiness (runbooks presence)
- `CC7.4` System monitoring endpoints (`/v1/ops/metrics`, `/v1/ops/slo`)
- `A1.1` Availability controls (SLA/failover/rate-limit posture)
- `A1.2` Backup + restore readiness
- `P4.1` Retention enforcement posture
- `SYSTEM.ENTITLEMENTS` Feature gate key presence
- `SYSTEM.PERF_GATES` Deterministic perf-gate configuration presence
- `SYSTEM.MIGRATIONS` Alembic version aligned with repository head

## Status Model

- `pass`: control criteria met
- `degraded`: partial evidence available but non-critical gap exists
- `fail`: criteria unmet

Snapshots persist both summary counts and full per-control evidence detail.
