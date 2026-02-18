# Evidence Bundles

## Purpose

Use this runbook to generate and export deterministic compliance evidence bundles for audits.

## Preconditions

- Admin API key for the target tenant.
- API and DB services running.
- Compliance automation enabled (`COMPLIANCE_ENABLED=true`).

## Steps

1. Create a snapshot:

```bash
curl -sS -X POST \
  -H "Authorization: Bearer ${ADMIN_API_KEY}" \
  http://localhost:8000/v1/admin/compliance/snapshots
```

2. List snapshots and capture `id`:

```bash
curl -sS \
  -H "Authorization: Bearer ${ADMIN_API_KEY}" \
  "http://localhost:8000/v1/admin/compliance/snapshots?limit=20"
```

Confirm the selected snapshot includes canonical fields: `captured_at`, `results_json`, and `artifact_paths_json`.

3. Download the bundle:

```bash
curl -sS -L \
  -H "Authorization: Bearer ${ADMIN_API_KEY}" \
  "http://localhost:8000/v1/admin/compliance/snapshots/${SNAPSHOT_ID}/download" \
  -o "compliance-bundle-${SNAPSHOT_ID}.zip"
```

## Bundle Contents

- `snapshot.json`
- `controls.json`
- `config_sanitized.json`
- `runbooks_index.json`
- `changelog_excerpt.md`
- `capacity_model_excerpt.md`
- `perf_gates_excerpt.json`
- `perf_report_summary.md`
- `ops_metrics_24h_summary.json`

## Invariants

- No plaintext secrets are included.
- Generated archives are also persisted to `var/evidence/<snapshot_id>.zip`.
