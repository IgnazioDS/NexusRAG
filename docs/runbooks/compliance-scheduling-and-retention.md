# Compliance Scheduling and Retention

## Purpose
- Document how compliance evaluations and evidence bundles are scheduled and retained.

## Scheduling
- `COMPLIANCE_EVAL_CRON` controls evaluation cadence (default daily).
- `COMPLIANCE_BUNDLE_CRON` controls periodic bundle creation (default weekly).

## Retention
- `COMPLIANCE_EVIDENCE_RETENTION_DAYS` governs how long evaluations and bundles are kept.
- Use `/v1/admin/maintenance/run?task=compliance_prune_old_evidence` to prune manually.

## Notes
- Evidence pruning is skipped when tenant-wide legal holds are active.
