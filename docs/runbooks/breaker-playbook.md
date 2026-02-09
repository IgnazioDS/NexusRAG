# Circuit Breaker Playbook

## Purpose
Circuit breakers prevent repeated slow/failing calls to external integrations by opening after a threshold of failures.

## States
- `closed`: normal operation.
- `open`: fast-fail with `INTEGRATION_UNAVAILABLE`.
- `half_open`: limited trial calls after the open window.

## When a Breaker Opens
1) Check `/v1/ops/metrics` for `circuit_breaker_state`.
2) Verify upstream status (AWS/GCP/OpenAI, webhook target).
3) Reduce canary percentage for the affected integration.
4) Use kill switch if errors are causing cascading failures.

## Recovery
1) Verify integration credentials and network status.
2) Wait for breaker to half-open and allow a test call.
3) If stable, the breaker will close automatically.

## Manual Actions
- Use kill switches to block traffic if breaker flaps repeatedly.
- Increase `CB_OPEN_SECONDS` temporarily if upstream is unstable.
