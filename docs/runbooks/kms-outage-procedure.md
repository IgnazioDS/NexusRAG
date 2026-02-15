# KMS Outage Procedure

## Detection
- Elevated `crypto_failures_total` or `KMS_UNAVAILABLE` errors.
- Failed encryption or decryption requests in logs.

## Mitigation
1. Verify KMS provider configuration and network access.
2. If required, set `CRYPTO_FAIL_MODE=open` to allow non-encrypted operations temporarily.
3. Resume `CRYPTO_FAIL_MODE=closed` once KMS is stable.

## Recovery
- Re-run any failed key rotation jobs.
- Re-encrypt sensitive artifacts created during the outage if required by policy.
