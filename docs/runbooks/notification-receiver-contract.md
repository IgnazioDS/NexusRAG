# Notification Receiver Operations

This runbook covers day-2 operations for the Notification Receiver Contract v1.0.

Spec reference: `docs/notification-receiver-contract.md`.

## Start Receiver Locally

```bash
make receiver-up
curl -s http://localhost:9001/health
```

## Inspect Delivery Data

```bash
curl -s "http://localhost:9001/received?limit=50"
make receiver-stats
curl -s http://localhost:9001/ops
```

## Troubleshoot Signature Failures

1. Confirm sender destination has a configured secret.
2. Confirm receiver `RECEIVER_SHARED_SECRET` matches sender destination secret.
3. Confirm receiver `RECEIVER_REQUIRE_SIGNATURE=true` only when secret is configured.
4. Check `/stats` counters:
   - `invalid_signature_count`
   - `missing_signature_count`
   - `signature_misconfig_count`

## Retry + DLQ Expectations

- Receiver `5xx` responses trigger sender retries.
- Receiver `4xx` responses are terminal and sender DLQs with `receiver_rejected`.
- Replay from DLQ creates a new `X-Notification-Id`; dedupe applies to that new id only.

## Deterministic Contract Validation

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
docker compose exec api make notify-e2e
```

