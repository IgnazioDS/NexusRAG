# Failover Rollback Runbook

## Rollback Criteria
- Promoted region is unstable after failover.
- Write verification fails and recovery actions do not restore health.
- Incident command approves returning primary to previous region.

## Steps
1. Request rollback token:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"purpose":"rollback","reason":"post-failover instability"}' \
  "http://localhost:8000/v1/ops/failover/request-token"
```
2. Execute rollback:
```
curl -s -X POST -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"token":"<TOKEN>","reason":"rollback to previous primary","force":false}' \
  "http://localhost:8000/v1/ops/failover/rollback"
```
3. Re-check status:
```
curl -s -H "Authorization: Bearer $ADMIN_API_KEY" \
  "http://localhost:8000/v1/ops/failover/status"
```

## Post-Rollback Checks
- `status=rolled_back` on rollback response.
- `active_primary_region` matches previous primary.
- Audit event `failover.rollback.completed` exists.

