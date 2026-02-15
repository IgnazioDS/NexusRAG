# SOC 2 Audit Prep

## Purpose
- Provide a repeatable checklist for SOC 2 evidence readiness.

## Steps
1. Confirm compliance controls evaluate without errors (`/v1/admin/compliance/evaluate`).
2. Generate an evidence bundle for the audit period (`/v1/admin/compliance/bundles`).
3. Verify bundle signature and checksum (`/v1/admin/compliance/bundles/{id}/verify`).
4. Archive `bundle.tar.gz` and `manifest.json` in the audit repository.
5. Export governance evidence (`/v1/ops/governance/evidence`) for cross-checking.

## Acceptance Criteria
- All required controls have pass/warn status and no unexpected errors.
- Bundle verification succeeds and checksum matches stored manifest.
