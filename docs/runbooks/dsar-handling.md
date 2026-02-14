# DSAR Handling

## Purpose
- Execute and audit DSAR export/delete/anonymize requests in a tenant-scoped and deterministic way.

## Steps
1. Create DSAR request with `POST /v1/admin/governance/dsar`.
2. Poll `GET /v1/admin/governance/dsar/{id}` until status is `completed|failed|rejected`.
3. For export requests, download artifact via `GET /v1/admin/governance/dsar/{id}/artifact`.
4. Verify `report_json`, `error_code`, and audit events for final evidence.

## Rejection Reasons
- `LEGAL_HOLD_ACTIVE`: an active hold supersedes destructive DSAR requests.
- `DSAR_REQUIRES_APPROVAL`: policy requires approval before destructive execution.
- `POLICY_DENIED`: policy-as-code denied request execution.

## Evidence Checklist
- DSAR request row with lifecycle timestamps.
- Export artifact + manifest checksum/signature metadata.
- Audit events: requested/running/completed/failed/rejected.
