# GA Readiness Checklist

## Command
Generate readiness artifacts:

```bash
make ga-checklist
```

## Categories
- Perf gate configuration present.
- Capacity model artifact exists.
- Security check targets available (`security-audit`, `security-lint`, `security-secrets-scan`).
- Retention configuration and last run timestamps.
- DR readiness signals from config and latest backup/drill records.
- Alerting + incident automation enabled with active rules.

## Output
- JSON: `var/ops/ga-checklist-<timestamp>.json`
- Markdown: `var/ops/ga-checklist-<timestamp>.md`
