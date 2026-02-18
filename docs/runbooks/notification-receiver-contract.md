# Notification Receiver Contract

This runbook defines the receiver-side contract for NexusRAG notification delivery.

## Required Headers

Receivers should parse these request headers on every webhook call:

- `X-Notification-Id`
- `X-Notification-Attempt` (1-based integer)
- `X-Notification-Event-Type`
- `X-Notification-Tenant-Id`
- `X-Notification-Signature` (optional unless signature enforcement is enabled)

## Signature Verification

When a destination has a configured shared secret, sender signs the **raw request body bytes** with HMAC-SHA256.

Header format:

- `X-Notification-Signature: sha256=<hex_digest>`

Verification pseudocode:

```python
expected = hmac_sha256(secret, raw_body_bytes).hexdigest()
provided = parse_header("sha256=<hex>")
if not compare_digest(expected, provided):
    reject()
```

Failure reasons used by the reference receiver:

- `missing_signature`
- `invalid_signature_format`
- `signature_mismatch`

## Dedupe Semantics

Delivery is at-least-once. Receivers must dedupe with `X-Notification-Id`.

- first receipt for id: process + mark seen
- later duplicates for same id: return `200` (idempotent accept)

DLQ replay creates a **new** notification job id, so replayed deliveries use a new `X-Notification-Id`.

## Receiver Response Semantics

- `2xx`: accepted (sender marks delivered)
- `5xx`: transient failure (sender retries with backoff)
- `4xx`: terminal rejection (sender marks DLQ with `reason=receiver_rejected`)

## Local Validation

Start stack:

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```

Run receiver E2E contract tests:

```bash
docker compose exec api make notify-e2e
```

Inspect reference receiver:

```bash
curl -s http://localhost:9001/health
curl -s "http://localhost:9001/received?limit=50"
```

