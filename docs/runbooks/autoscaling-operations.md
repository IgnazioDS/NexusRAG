# Autoscaling Operations

## Purpose

Operate SLA-driven autoscaling profiles and action workflows safely using dry-run and apply modes.

## Pre-checks

1. Confirm autoscaling is enabled:
   - `AUTOSCALING_ENABLED=true`
2. Confirm executor mode:
   - `AUTOSCALING_EXECUTOR=noop` (current default)
3. Confirm profile bounds are valid:
   - `min_replicas <= max_replicas`
   - positive `step_up`, `step_down`
4. Confirm cooldown/hysteresis are set:
   - `cooldown_seconds`
   - `AUTOSCALING_HYSTERESIS_PCT`

## Standard Workflow

1. Create/update profile:
   - `POST /v1/admin/sla/autoscaling/profiles`
   - `PATCH /v1/admin/sla/autoscaling/profiles/{id}`
2. Run dry-run recommendation:
   - `POST /v1/admin/sla/autoscaling/evaluate`
3. Inspect persisted recommendation history:
   - `GET /v1/admin/sla/autoscaling/actions`
4. Apply action if approved:
   - `POST /v1/admin/sla/autoscaling/apply`

## Cooldown Handling

- Apply returns `SLA_AUTOSCALING_COOLDOWN_ACTIVE (409)` when cooldown is active.
- Wait for cooldown expiry or reduce profile cooldown in controlled change.

## Failure Modes

- `SLA_AUTOSCALING_PROFILE_INVALID (422)`: profile bounds/fields are invalid.
- `SLA_AUTOSCALING_EXECUTOR_UNAVAILABLE (503)`: backend adapter unavailable.
- `signal_quality=degraded`: recommendation quality reduced; verify telemetry inputs first.

## Audit Trace

- `sla.autoscaling.recommended`
- `sla.autoscaling.applied`
- Related incident/breach events when scaling follows SLA breaches.
