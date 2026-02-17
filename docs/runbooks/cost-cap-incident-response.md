# Cost Cap Incident Response

## Purpose
Guide operators through handling a tenant hitting a cost hard cap or repeated cost budget warnings.

## Detection
- Alerts from `cost.cap.triggered` or `cost.warn.triggered` audit events.
- Support ticket reporting `COST_BUDGET_EXCEEDED` responses.
- Dashboard header values show `X-Cost-Status: capped` or `warn`.

## Immediate Actions
1. Confirm tenant scope and active budget settings:
   - `GET /v1/admin/costs/budget`
2. Verify recent spend and breakdown:
   - `GET /v1/admin/costs/spend/summary?period=month`
   - `GET /v1/admin/costs/spend/breakdown?period=month&by=component`
3. Check recent budget snapshots in the database (`tenant_budget_snapshots`) for trigger timestamps.

## Mitigation Options
- Increase monthly budget or set a temporary override:
  - `PATCH /v1/admin/costs/budget` with `current_month_override_usd`.
- Switch to `hard_cap_mode=degrade` if partial service is acceptable.
- Reduce high-cost features by disabling TTS or lowering top_k at the client.

## Verification
- Re-run the blocked operation; confirm `X-Cost-Status` transitions to `ok` or `warn`.
- Ensure new audit events show `cost.budget.updated` and the latest `cost.cap.triggered` is cleared.

## Communication
- Notify the tenant with the observed spend and the change applied.
- Document the reason for any override and set a reminder to revert it.

## Post-Incident Follow-Up
- Review pricing catalog for accuracy and overlap.
- Validate tenant chargeback report totals for the affected period.
- Add guardrail tests if a new failure mode was uncovered.
