# Backup Key Rotation

## Scope
Rotate backup encryption and signing keys without breaking restore validation.

## Steps
1) Generate new keys and store them in your secret manager.
2) Update environment variables:
   - `BACKUP_ENCRYPTION_KEY`
   - `BACKUP_SIGNING_KEY`
3) Deploy configuration changes.
4) Trigger a new backup and confirm success.
5) Run a restore drill using the new keys.

## Backward Compatibility
- Keep old keys available until all older backups age out.
- If `RESTORE_REQUIRE_SIGNATURE=true`, ensure old signatures remain verifiable.

## Validation
- `/v1/ops/dr/readiness` should report `status: ready`.
- New backups should have valid signatures and decrypt successfully.

