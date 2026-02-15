# Evidence Bundle Verification

## Purpose
- Validate SOC 2 evidence bundles before distribution to auditors.

## Steps
1. Fetch bundle metadata: `GET /v1/admin/compliance/bundles/{id}`.
2. Verify the bundle: `POST /v1/admin/compliance/bundles/{id}/verify`.
3. Confirm checksum and signature in the response.

## Failure Handling
- If verification fails, regenerate the bundle and re-run verification.
- Inspect `manifest.json` and ensure the signing key configuration is correct.
