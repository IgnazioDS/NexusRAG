# Restore Drill Checklist

## Pre-Drill
- Confirm latest backup succeeded in `/v1/ops/dr/backups`.
- Ensure signing/encryption keys are available to the drill environment.
- Verify `BACKUP_LOCAL_DIR` (or storage adapter) access.

## Drill Steps
1) Trigger the drill:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/dr/restore-drill"
```
2) Confirm drill completion in `/v1/ops/dr/readiness`.
3) Review drill report for validation errors.

## Pass/Fail Criteria
Pass:
- Manifest signature verified (if enabled)
- Checksums match
- No validation errors

Fail:
- Missing artifacts or checksum mismatch
- Invalid signature
- Unreadable backup artifacts

## Evidence
- Record `restore_drills` row with timestamps and `rto_seconds`.
- Capture readiness response for audit trails.

