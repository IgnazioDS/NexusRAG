# Notification Receiver Contract v1.0

This document defines the sender/receiver interoperability contract for NexusRAG notification webhooks.

## Delivery Guarantees

- Delivery mode: **at-least-once**.
- Idempotency key: `X-Notification-Id`.
- Redelivery of the same job keeps the same `X-Notification-Id`.
- DLQ replay creates a new job id, therefore a **new** `X-Notification-Id`.

Receiver requirement:

- Treat `X-Notification-Id` as the dedupe key.
- Accept duplicate deliveries idempotently with `2xx`.

## Required Headers

- `X-Notification-Id`
- `X-Notification-Attempt` (1-based integer)
- `X-Notification-Event-Type`
- `X-Notification-Tenant-Id`

Optional:

- `X-Notification-Signature` (`sha256=<hex>`)
- `X-Notification-Timestamp` (ISO8601 UTC; optional in v1.0)

## Canonical Signature Scheme

- Algorithm: `HMAC-SHA256`
- Input: **raw HTTP request body bytes**
- Header format: `X-Notification-Signature: sha256=<hex>`

Python pseudocode:

```python
expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
provided = header_value.removeprefix("sha256=")
valid = hmac.compare_digest(expected, provided)
```

Notes:

- Always use constant-time comparison (`compare_digest`).
- Never verify against re-serialized JSON; use raw bytes exactly as received.
- If `X-Notification-Timestamp` is used, enforce skew tolerance in receiver config.

## Receiver Response Semantics

- `2xx`: accepted; sender marks job delivered.
- `5xx`: transient failure; sender retries with deterministic backoff.
- `4xx`: receiver rejected payload/headers/signature; sender treats as terminal and DLQs with `receiver_rejected`.

## Compatibility Matrix

| Profile | require_signature | shared_secret | Behavior |
| --- | --- | --- | --- |
| `strict_signed` | true | set | Signed requests accepted; unsigned rejected |
| `permissive_unsigned` | false | unset | Unsigned requests accepted |
| `misconfigured_secret` | true | unset | Signed requests fail (`secret_missing`) |

Fixture source: `nexusrag/tests/fixtures/notification_receiver_compatibility.json`.

## Receiver Implementation API

Module: `nexusrag/services/notifications/receiver_contract.py`

- `parse_required_headers(headers) -> ReceiverHeaders`
- `compute_signature(raw_body, secret) -> str`
- `verify_signature(headers, raw_body, secret) -> VerificationResult`
- `payload_sha256(raw_body) -> str`
- `NotificationDedupeStore` + `SQLiteNotificationDedupeStore`

## Security + Rotation Guidance

- Store destination secrets encrypted-at-rest via platform keyring.
- Rotate destination secrets by:
  1. Create new secret in destination config.
  2. Deploy receiver with matching secret.
  3. Validate signed deliveries.
- Never log shared secrets or raw credentials.

## Interop Notes (Other Languages)

Any language/runtime is compatible if it can:

- Read raw body bytes before JSON parsing.
- Compute HMAC-SHA256 over raw bytes.
- Compare with constant-time function.
- Persist dedupe key (`X-Notification-Id`) atomically.
- Return `2xx/4xx/5xx` with semantics above.

