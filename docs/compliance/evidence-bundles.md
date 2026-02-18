# Evidence Bundles

Compliance bundles are generated from persisted snapshots using:

- `POST /v1/admin/compliance/snapshot`
- `GET /v1/admin/compliance/bundle/{snapshot_id}.zip`

## Bundle Contents

- `snapshot.json`
- `controls.json`
- `config_sanitized.json`
- `runbooks_index.json`
- `changelog_excerpt.md`
- `capacity_model_excerpt.md`
- `perf_gates_excerpt.json`

## Redaction Rules

- Config export is sanitized through audit redaction logic.
- Sensitive keys (`api_key`, `token`, `secret`, `password`, etc.) are always replaced with `[REDACTED]`.
- Bundle generation does not persist temporary unredacted files.

## Operational Notes

- Snapshots are tenant-scoped.
- Bundle endpoint enforces admin authentication and tenant isolation.
- Snapshot/bundle actions are auditable events.
