# Key Compromise Response

## Immediate Actions
1. Set incident context and notify stakeholders.
2. Rotate tenant keys immediately with `force=true` if rotation is already in progress.
3. Pause non-essential workloads if KMS access is unstable.

## Rotation Procedure
- `POST /v1/admin/crypto/keys/{tenant_id}/rotate` with `reencrypt=true`.
- Monitor the rotation job until completion.

## Post-rotation Validation
- Verify new key is `active` and old key is `retired`.
- Confirm decryption works for recent encrypted artifacts.

## Audit Evidence
- Collect audit events for `crypto.key.created`, `crypto.key.activated`, `crypto.key.retired`, and rotation events.
