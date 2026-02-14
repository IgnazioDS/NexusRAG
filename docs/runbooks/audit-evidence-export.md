# Audit Evidence Export

## Purpose
- Provide machine-readable evidence for governance/compliance audits.

## Evidence Endpoint
- `GET /v1/ops/governance/evidence?window_days=30`

## Bundle Sections
- `retention_runs`
- `dsar_requests`
- `legal_holds`
- `policy_changes`

## Recommended Workflow
1. Generate evidence bundle for requested audit window.
2. Export DSAR artifacts for completed export requests when needed.
3. Correlate with audit events by `request_id` and event type.
4. Archive evidence bundle in your compliance repository.

## Minimum Acceptance
- At least one retention run for active tenants.
- DSAR outcomes include completed/rejected traces.
- Hold lifecycle changes are visible.
- Policy changes include rule key, priority, and updated timestamp.
