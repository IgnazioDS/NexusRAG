# Retention and Anonymization

## Purpose
- Apply tenant retention policies safely with legal-hold supersession.

## Policy Controls
- `messages_ttl_days`
- `checkpoints_ttl_days`
- `audit_ttl_days`
- `documents_ttl_days`
- `backups_ttl_days`
- `hard_delete_enabled`
- `anonymize_instead_of_delete`

## Execution
1. Read/update policy via `/v1/admin/governance/retention/policy`.
2. Trigger run via `/v1/admin/governance/retention/run`.
3. Read run report via `/v1/admin/governance/retention/report`.

## Behavior Rules
- Active legal hold always wins over TTL pruning.
- If hard-delete mode is off, records are anonymized where supported.
- Backup prune skips manifest sets under `backup_set` legal hold.

## Operator Checks
- Verify per-category counts in `report_json`.
- Verify hold-skipped counts for expected scopes.
- Verify audit events for started/completed/failed retention runs.
