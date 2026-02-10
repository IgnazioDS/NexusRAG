# Disaster Recovery: Backup & Restore

## Goals
- Protect production data and configuration.
- Provide repeatable restore steps with integrity validation.
- Meet RTO/RPO targets with measurable drill outcomes.

## Backup Types
- `full`: database logical dump (`db_full.sql.gz`)
- `schema`: schema-only dump (`db_schema.sql.gz`)
- `metadata`: JSON snapshot of plans/entitlements, API key metadata, quota usage, rollouts

## Create Backups
```
python scripts/backup_create.py --type all
```

Artifacts are written under `BACKUP_LOCAL_DIR` with a `manifest.json` and optional signature.

## Restore (Dry-Run)
```
python scripts/backup_restore.py \
  --manifest ./backups/<job>/manifest.json \
  --components all \
  --dry-run
```

## Restore (Destructive)
```
python scripts/backup_restore.py \
  --manifest ./backups/<job>/manifest.json \
  --components db,schema \
  --allow-destructive
```

## Integrity Checks
- Manifest schema validation
- SHA256 checksums for each artifact
- HMAC signature verification (if enabled)

## Troubleshooting
- `BACKUP_FAILED`: check `pg_dump` availability and DB connectivity
- `RESTORE_VALIDATION_FAILED`: verify manifests and signature keys
- `RESTORE_DESTRUCTIVE_CONFIRMATION_REQUIRED`: rerun with `--allow-destructive`

