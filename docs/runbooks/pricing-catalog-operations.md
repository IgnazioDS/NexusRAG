# Pricing Catalog Operations

## Purpose
Maintain deterministic cost calculations by managing pricing catalog entries safely.

## Before You Start
- Confirm the target provider/component and rate type.
- Ensure no overlapping active pricing windows exist for the same provider/component/rate_type.

## Add a New Rate
1. Draft the new rate entry (versioned, effective dates):

```
POST /v1/admin/costs/pricing/catalog
{
  "version": "v2026.02",
  "provider": "internal",
  "component": "llm",
  "rate_type": "per_1k_tokens",
  "rate_value_usd": 0.0025,
  "effective_from": "2026-02-01T00:00:00Z",
  "effective_to": null,
  "active": true
}
```

2. Verify the entry appears in the catalog:
   - `GET /v1/admin/costs/pricing/catalog?active=true`

## Deactivate an Old Rate
- Insert a new entry with a later `effective_from` and set the old entry to `active=false` via a DB migration if needed.
- Avoid overlapping `effective_from/effective_to` windows when `active=true`.

## Validation Checklist
- Only one active rate per provider/component/rate_type at any point in time.
- `effective_to` is after `effective_from` when provided.
- Rates are expressed in USD with 6 decimal places where needed.

## Rollback
- Mark the new entry as inactive and restore the previous entry if regression is detected.
- Re-run cost calculations for a limited period if chargeback data was impacted.

## Notes
- Missing active pricing rates return `COST_PRICING_NOT_FOUND` on list queries with `active=true`.
- Metering continues in best-effort mode with cost set to 0 when pricing is missing.
