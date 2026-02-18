# Key Rotation

## Scope

Platform keyring (`/v1/admin/keyring` and `/v1/admin/keys` compatibility path) and API key credential rotation.

## Platform keyring flow

1. Rotate a key: `POST /v1/admin/keyring/rotate?purpose=signing|encryption|backup_signing|backup_encryption|webhook_signing`
2. Validate new key metadata in `GET /v1/admin/keyring`
3. Retire older key if needed: `POST /v1/admin/keyring/{key_id}/retire`

## API key flow

1. Rotate credential using script: `python scripts/rotate_api_key.py <old_key_id>`
2. Optional: keep previous key active during phased rollout with `--keep-old-active`
3. Distribute new plaintext key securely (shown once)
4. Confirm audit event `auth.api_key.rotated`
5. Confirm old key is revoked and cannot authenticate (unless phased rollout is intentional)

## Verification

- `python scripts/list_api_keys.py --tenant <tenant_id> --inactive-only`
- `GET /v1/admin/api-keys?include_only_inactive=true`
- Audit search for `auth.api_key.expired`, `auth.api_key.rotated`, `security.keyring.rotated`

## Safety invariants

- Never store plaintext API keys in persistence.
- Platform key material is encrypted before DB write.
- Retire/revoke operations are idempotent.
