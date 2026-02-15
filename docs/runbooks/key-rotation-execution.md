# Key Rotation Execution

## Preconditions
- Verify `CRYPTO_ENABLED=true` and the target tenant has an active key.
- Confirm no active rotation job is already running for the tenant.
- Inform stakeholders about potential transient decryption latency during re-encryption.

## Rotation Steps
1. Request rotation:
   - `POST /v1/admin/crypto/keys/{tenant_id}/rotate` with `reencrypt=true`.
2. Monitor rotation job:
   - `GET /v1/admin/crypto/rotation-jobs/{job_id}` until `status=completed`.
3. Verify key status:
   - `GET /v1/admin/crypto/keys/{tenant_id}` and confirm previous key is `retired`.

## Rollback
- If rotation fails, pause or cancel the job, then re-run after resolving KMS issues.

## Notes
- Rotation does not delete data; it re-encrypts envelope payloads.
- One active rotation job per tenant is enforced.
