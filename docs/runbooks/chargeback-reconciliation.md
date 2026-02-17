# Chargeback Reconciliation

## Purpose
Validate chargeback reports and reconcile totals with raw usage cost events.

## Inputs
- Report period (`period_start`, `period_end`)
- Tenant identifier

## Generate and Review Report
1. Generate a report:

```
POST /v1/admin/costs/chargeback/generate?period_start=...&period_end=...
```

2. Fetch the report list and confirm the new report ID:
   - `GET /v1/admin/costs/chargeback/reports`

3. Inspect the report detail:
   - `GET /v1/admin/costs/chargeback/reports/{id}`

## Reconciliation Steps
- Compare `total_usd` to the sum of `usage_cost_events` in the same period.
- Validate breakdown totals by component/provider/route_class.
- Confirm any budget warnings/caps correspond to spikes in spend.

## Handling Discrepancies
- Verify pricing catalog entries for the period (active rates, effective windows).
- Check for delayed ingestion/worker events that may land after the report window.
- Regenerate the report if pricing or data corrections were applied.

## Audit Trail
- Ensure `cost.chargeback.generated` events exist for each report.
- Record any manual adjustments and the reason in an internal ticket.
