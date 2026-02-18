# Compliance Snapshot Operations

## Generate snapshot

`POST /v1/admin/compliance/snapshot` or `POST /v1/admin/compliance/snapshots`

Expected result: snapshot id, summary status, and per-control results persisted.

## List and inspect snapshots

- `GET /v1/admin/compliance/snapshots?limit=20`
- `GET /v1/admin/compliance/snapshots/{id}`

## Export evidence bundle

`GET /v1/admin/compliance/bundle/{snapshot_id}.zip` or `GET /v1/admin/compliance/snapshots/{snapshot_id}/download`

Verify bundle includes:

- `snapshot.json`
- `controls.json`
- `config_sanitized.json`
- `runbooks_index.json`
- `changelog_excerpt.md`
- `capacity_model_excerpt.md`
- `perf_gates_excerpt.json`
- `perf_report_summary.md`
- `ops_metrics_24h_summary.json`

## Validation checks

- Secrets are redacted in `config_sanitized.json`
- Snapshot status matches control result aggregation
- Audit events emitted for snapshot and bundle generation
- Archive is persisted to `var/evidence/<snapshot_id>.zip`
