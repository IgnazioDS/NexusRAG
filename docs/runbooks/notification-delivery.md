# Notification Delivery

## Purpose
- Restore or validate alert/incident notification delivery when jobs are delayed or failing.

## Signals
- `/v1/ops/operability` shows:
  - `jobs_queued`
  - `jobs_failed_last_hour`
- `/v1/admin/notifications/jobs?status=retrying` lists pending retries.
- Audit events:
  - `notification.job.enqueued`
  - `notification.job.succeeded`
  - `notification.job.failed`
  - `notification.job.gave_up`

## Triage Steps
1. Confirm worker is running:
   - `docker compose logs --tail=200 notification_worker`
   - `docker compose ps notification_worker`
2. Inspect failed jobs:
   - `GET /v1/admin/notifications/jobs?status=gave_up`
3. Validate destination routing:
   - `GET /v1/admin/notifications/destinations?tenant_id=<tenant>`
   - Fallback config: `NOTIFY_WEBHOOK_URLS_JSON`
4. Retry a job:
   - `POST /v1/admin/notifications/jobs/{id}/retry`
5. Check queue settings:
   - `NOTIFY_QUEUE_NAME`
   - `NOTIFY_WORKER_POLL_INTERVAL_S`
   - `NOTIFY_REQUEUE_BATCH_SIZE`

## Recovery
1. Fix destination endpoint/connectivity.
2. Trigger retries for affected jobs.
3. Watch `jobs_failed_last_hour` trend down to baseline.

## Invariants
- Delivery is best-effort and async; request path must not block.
- Destination precedence is tenant rows first, global fallback second.
- Dedupe window suppresses duplicate jobs for same incident/destination/event bucket.
- ARQ queue carries `job_id` only; `notification_jobs` remains source of truth.
- Job attempts are immutable rows in `notification_attempts`.
