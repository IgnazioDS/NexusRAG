# Retention Proof

## Purpose

Produce tenant-scoped retention proof for governance and regulated buyer questionnaires.

## Preconditions

- Admin API key for the tenant.
- Retention settings configured for the tenant.

## Run Unified Prune

```bash
curl -sS -X POST \
  -H "Authorization: Bearer ${ADMIN_API_KEY}" \
  "http://localhost:8000/v1/admin/governance/retention/run?task=prune_all"
```

Expected fields:

- `last_run_at`
- `items_pruned_by_table`
- `configured_retention_days`
- `next_scheduled_run`

## Fetch Current Retention Proof Status

```bash
curl -sS \
  -H "Authorization: Bearer ${ADMIN_API_KEY}" \
  "http://localhost:8000/v1/admin/governance/retention/status"
```

## Invariants

- Response is tenant-scoped and does not leak cross-tenant run metadata.
- Unified prune path records retention maintenance evidence in `retention_runs`.
