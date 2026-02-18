# Deploy Preflight

## Command
Run deterministic preflight before rollout:

```bash
make preflight
```

## Checks
- Alembic DB revision equals repository head revision.
- Required runtime environment variables are present (values are never printed).
- Redis reachability for queue/rate-limit paths.
- Worker heartbeat status (warn/fail based on config).
- Ops route registration (`/metrics`, `/slo`, `/health`).
- Latest compliance snapshot is not `fail`.

## Output
- JSON artifact: `var/ops/preflight.json`
- Non-zero exit code on failing checks.
