# Legal Hold Procedure

## Purpose
- Prevent retention, backup prune, and DSAR destructive workflows from deleting held data.

## Create Hold
1. Call `POST /v1/admin/governance/legal-holds`.
2. Set `scope_type` and `scope_id` (`scope_id` omitted for tenant scope).
3. Include business reason and optional `expires_at`.

## Validate Enforcement
- Run retention via `POST /v1/admin/governance/retention/run`.
- Confirm report category `skipped_hold` counters.
- Confirm destructive DSAR requests return `LEGAL_HOLD_ACTIVE`.

## Release Hold
1. Call `POST /v1/admin/governance/legal-holds/{id}/release`.
2. Re-run retention or DSAR flow to confirm execution resumes.

## Audit Evidence
- Hold create/release events.
- Retention skip-hold events.
- DSAR rejected events when hold blocks execution.
