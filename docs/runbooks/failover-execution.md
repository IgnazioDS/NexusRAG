# Failover Execution Runbook

## Preconditions
- Confirm `/v1/ops/failover/readiness` reports `recommendation=promote_candidate`.
- Confirm blockers list is empty, or use force mode only with incident commander approval.
- Confirm cooldown is not active from `/v1/ops/failover/status`.

## Steps
1. Request a promotion token:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"purpose":"promote","reason":"primary unavailable"}' \
  "http://localhost:8000/v1/ops/failover/request-token"
```
2. Promote with the one-time token:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"target_region":"ap-southeast-1","token":"<TOKEN>","reason":"incident failover","force":false}' \
  "http://localhost:8000/v1/ops/failover/promote"
```
3. Verify cluster state:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/failover/status"
```

## Verification Checklist
- `active_primary_region` matches target region.
- `epoch` incremented.
- `freeze_writes=false` after verification.
- Audit event `failover.promote.completed` exists.

