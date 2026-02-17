# SLA Breach Response

## Purpose

Respond to sustained tenant SLA breaches (`latency`, `availability`, `saturation`, `error_budget`) detected by the SLA policy engine.

## Triggers

- `sla.breach.detected`
- `sla.incident.opened`
- Elevated `X-SLA-Status: breached` across tenant traffic
- Repeated `sla.enforcement.degraded` or `sla.enforcement.shed`

## Immediate Actions

1. Confirm impacted tenant and route class:
   - `GET /v1/admin/sla/incidents`
   - `GET /v1/admin/sla/measurements?window=1m&route_class=run`
2. Verify assigned policy and enforcement mode:
   - `GET /v1/admin/sla/assignments/{tenant_id}`
   - `GET /v1/admin/sla/policies`
3. Check if mitigation is already active:
   - Run SSE events: `sla.warn`, `sla.degrade.applied`, `sla.shed`
   - Response headers: `X-SLA-Decision`, `X-SLA-Status`
4. If shedding is excessive, switch policy to `warn` or `observe` temporarily.

## Containment Levers

- Enable/disable policy: `POST /v1/admin/sla/policies/{id}/enable|disable`
- Patch enforcement mode: `PATCH /v1/admin/sla/policies/{id}`
- Reassign tenant policy: `PATCH /v1/admin/sla/assignments/{tenant_id}`
- Trigger autoscaling dry-run/apply:
  - `POST /v1/admin/sla/autoscaling/evaluate`
  - `POST /v1/admin/sla/autoscaling/apply`

## Resolution

1. Confirm metrics recovery in `1m` and `5m` windows.
2. Resolve incident:
   - `POST /v1/admin/sla/incidents/{id}/resolve`
3. Capture post-incident notes:
   - breaching objective
   - mitigation applied
   - autoscaling recommendations/actions

## Evidence

- Audit events:
  - `sla.breach.detected`
  - `sla.incident.opened|resolved`
  - `sla.enforcement.warned|degraded|shed`
  - `sla.autoscaling.recommended|applied`
