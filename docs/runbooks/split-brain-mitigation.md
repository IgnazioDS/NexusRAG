# Split-Brain Mitigation Runbook

## Detection Signals
- `/v1/ops/failover/readiness` returns blocker `SPLIT_BRAIN_RISK`.
- Peer region still reports healthy primary ownership.
- Conflicting writes observed across regions.

## Immediate Actions
1. Enable write freeze:
```
curl -s -X PATCH -H "Authorization: Bearer $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"freeze":true,"reason":"split-brain containment"}' \
  "http://localhost:8000/v1/ops/failover/freeze-writes"
```
2. Verify freeze state from `/v1/ops/failover/status`.
3. Validate network partition and peer health before any forced promotion.

## Recovery Path
- Prefer restoring single-primary consensus first.
- Use forced promotion only with explicit incident approval and documented risk.
- Keep freeze enabled until post-promotion verification is complete.

