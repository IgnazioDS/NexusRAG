# Key Rotation

## Scope

Platform keyring (`/v1/admin/keys`) and API key credential rotation.

## Platform keyring flow

1. Rotate a key: `POST /v1/admin/keys/rotate?purpose=signing|encryption`
2. Validate new key metadata in `GET /v1/admin/keys`
3. Retire older key if needed: `POST /v1/admin/keys/{key_id}/retire`

## API key flow

1. Rotate credential using script: `python scripts/rotate_api_key.py <old_key_id>`
2. Distribute new plaintext key securely (shown once)
3. Confirm audit event `auth.api_key.rotated`
4. Confirm old key is revoked and cannot authenticate

## Verification

- `GET /v1/self-serve/api-keys/inactive-report`
- Audit search for `auth.api_key.expired`, `auth.api_key.rotated`, `security.keyring.rotated`

## Safety invariants

- Never store plaintext API keys in persistence.
- Platform key material is encrypted before DB write.
- Retire/revoke operations are idempotent.
