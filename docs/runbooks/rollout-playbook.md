# Rollout Playbook

## Canary Progression
Suggested progression for risky integrations:
1% -> 5% -> 25% -> 100%

## Checklist
1) Set canary percentage in `/v1/admin/rollouts/canary`.
2) Monitor `/v1/ops/slo` and `/v1/ops/metrics`.
3) Confirm error budget burn stays below 1.0.
4) Increase canary only after stable window (15-30 minutes).

## Abort Conditions
- Error budget burn rate > 1.0.
- Circuit breaker opens repeatedly.
- Significant latency regression on `/v1/run` or `/v1/ui/bootstrap`.

## Rollback
- Drop canary to 0.
- Enable kill switch if needed.
