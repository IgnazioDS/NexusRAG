# Alerting Triage

## Scope
Use this runbook when `/v1/admin/alerts/evaluate` returns triggered alerts or when `alert.triggered` audit events increase.

## Steps
1. Fetch current rules: `GET /v1/admin/alerts/rules`.
2. Evaluate with current telemetry window: `POST /v1/admin/alerts/evaluate?window=5m`.
3. Confirm related incidents: `GET /v1/admin/incidents?status=open`.
4. Validate runtime headers on `/v1/run` (`X-SLA-*`) to confirm enforce/degrade/shed state.
5. If false positive, patch threshold safely with `PATCH /v1/admin/alerts/rules/{rule_id}`.

## Invariants
- Do not disable all high/critical rules simultaneously.
- Keep one active worker heartbeat rule and one breaker-open rule enabled.
- Preserve audit evidence (`alert.triggered`, `alert.suppressed`) during tuning.
