# Load Shedding Playbook

## Purpose

Guide controlled handling of SLA-enforced load shedding (`SLA_SHED_LOAD`) on `/v1/run` and ingest operations.

## Indicators

- HTTP `503` with error code `SLA_SHED_LOAD`
- SSE `sla.shed` event
- `X-SLA-Decision: shed`
- Spike in `sla.enforcement.shed` audit events

## Verification Steps

1. Confirm sustained breach windows:
   - `GET /v1/admin/sla/measurements?window=1m&route_class=run`
2. Confirm active policy mode:
   - `GET /v1/admin/sla/assignments/{tenant_id}`
   - `GET /v1/admin/sla/policies`
3. Confirm incident state:
   - `GET /v1/admin/sla/incidents`

## Recovery Options

1. Preferred: reduce pressure
   - run autoscaling evaluate/apply
   - reduce expensive traffic paths for impacted tenant
2. Temporary policy relief
   - set enforcement to `warn` (keep visibility, stop shedding)
   - or set to `observe` for emergency bypass
3. Keep guardrails but degrade first
   - set `mitigation.allow_degrade=true`
   - configure fallback providers and lower token/top_k caps

## Exit Criteria

- `X-SLA-Status` transitions from `breached` to `warning|healthy`
- No new shed events in recent windows
- Incident resolved via:
  - `POST /v1/admin/sla/incidents/{id}/resolve`

## Postmortem Notes

- Trigger condition (latency/availability/saturation/error budget)
- Why shedding was chosen over degrade
- Autoscaling decisions and cooldown behavior
- Policy or profile adjustments needed to prevent recurrence
