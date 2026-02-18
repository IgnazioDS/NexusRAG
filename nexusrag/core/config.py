from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


# Keep embedding dimension centralized to prevent drift across DB and retrieval logic.
EMBED_DIM = 768


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "nexusrag"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://nexusrag:nexusrag@localhost:5432/nexusrag"

    # Redis connection for ingestion queue and worker coordination.
    redis_url: str = "redis://localhost:6379/0"
    # Keep queue name configurable for multi-environment isolation.
    ingest_queue_name: str = "ingest"
    # Limit retries for transient ingestion failures to avoid infinite loops.
    ingest_max_retries: int = 3
    # Inline mode executes ingestion immediately for deterministic tests.
    ingest_execution_mode: str = "queue"
    # Emit worker heartbeats for ops health and alerting.
    worker_heartbeat_interval_s: int = 10
    # Treat stale heartbeats as degraded to surface worker outages.
    worker_heartbeat_stale_after_s: int = 60
    # Require API key auth for all protected endpoints by default.
    auth_enabled: bool = True
    # Allow legacy X-Tenant-Id + X-Role only when explicitly enabled for dev.
    auth_dev_bypass: bool = False
    # Header used to carry the bearer API key.
    auth_api_key_header: str = "Authorization"
    # Small cache window to reduce auth DB lookups without delaying revocations too long.
    auth_cache_ttl_s: int = 15
    # Toggle ABAC evaluation on top of RBAC checks.
    authz_abac_enabled: bool = True
    # Default to deny when no ABAC policy matches.
    authz_default_deny: bool = True
    # Allow admin role to bypass document ACLs when explicitly enabled.
    authz_admin_bypass_document_acl: bool = False
    # Enforce maximum serialized policy size to bound evaluation cost.
    authz_max_policy_bytes: int = 16384
    # Enforce maximum policy nesting depth to keep evaluation deterministic.
    authz_max_policy_depth: int = 8
    # Enable ABAC policy simulation endpoint.
    authz_simulation_enabled: bool = True
    # Require tenant predicates on tenant-scoped repository queries.
    authz_require_tenant_predicate: bool = True
    # Allow wildcard policies on both resource_type and action only when enabled.
    authz_allow_wildcards: bool = False
    # Toggle enterprise SSO endpoints and login flows.
    sso_enabled: bool = True
    # Comma-delimited allowed hosts for post-login redirects.
    sso_allowed_redirect_hosts: str = ""
    # Bound state/nonce lifetimes to reduce replay risk.
    sso_state_ttl_seconds: int = 600
    sso_nonce_ttl_seconds: int = 600
    # Allow bounded clock skew for OIDC token validation.
    sso_clock_skew_seconds: int = 120
    # Default session lifetime for SSO-issued tokens.
    sso_session_ttl_hours: int = 8
    # Allow public IdP discovery when explicitly enabled.
    sso_public_discovery_enabled: bool = False
    # Toggle SCIM provisioning endpoints.
    scim_enabled: bool = True
    # Default SCIM token lifetime in days.
    scim_token_ttl_days: int = 365
    # Pagination defaults for SCIM list endpoints.
    scim_default_page_size: int = 50
    scim_max_page_size: int = 200
    # Require dual-control for role escalations when enabled.
    identity_dual_control_required: bool = False
    # Toggle rate limiting for abuse protection and capacity control.
    rate_limit_enabled: bool = True
    # Choose fail-open or fail-closed behavior when Redis is unavailable.
    rl_fail_mode: str = "open"
    # Configure per-key and per-tenant rate limits for /run (strict path).
    rl_key_run_rps: float = 1
    rl_key_run_burst: int = 5
    rl_tenant_run_rps: float = 3
    rl_tenant_run_burst: int = 15
    # Configure per-key and per-tenant rate limits for mutations.
    rl_key_mutation_rps: float = 2
    rl_key_mutation_burst: int = 10
    rl_tenant_mutation_rps: float = 5
    rl_tenant_mutation_burst: int = 25
    # Configure per-key and per-tenant rate limits for read endpoints.
    rl_key_read_rps: float = 5
    rl_key_read_burst: int = 20
    rl_tenant_read_rps: float = 15
    rl_tenant_read_burst: int = 60
    # Configure per-key and per-tenant rate limits for ops/audit endpoints.
    rl_key_ops_rps: float = 2
    rl_key_ops_burst: int = 10
    rl_tenant_ops_rps: float = 4
    rl_tenant_ops_burst: int = 20
    # Prefix rate limit keys to avoid collisions with other Redis data.
    rl_redis_prefix: str = "nexusrag:rl"
    # Toggle billing webhook emission for quota events.
    billing_webhook_enabled: bool = False
    billing_webhook_url: str | None = None
    billing_webhook_secret: str | None = None
    # Keep webhook timeouts short to avoid blocking API responses.
    billing_webhook_timeout_ms: int = 2000
    # Toggle cost governance features (metering, budgets, chargeback).
    cost_governance_enabled: bool = True
    # Default warn ratio for budgets when tenant config omits one.
    cost_default_warn_ratio: float = 0.8
    # Default hard cap mode when tenant config omits one.
    cost_default_hard_cap_mode: str = "block"
    # Allow disabling TTS first when degrading for budget control.
    cost_degrade_enable_tts_disable: bool = True
    # Minimum top_k used when degrading retrieval requests.
    cost_degrade_min_top_k: int = 3
    # Cap output tokens in degrade mode to bound generation cost.
    cost_degrade_max_output_tokens: int = 512
    # Enable fallback estimators when providers do not supply usage metadata.
    cost_estimator_enabled: bool = True
    # Approximate characters per token for deterministic estimation.
    cost_estimator_token_chars_ratio: float = 4.0
    # Default window for cost timeseries endpoints.
    cost_timeseries_default_days: int = 30
    # Toggle performance harness and deterministic perf gates.
    perf_mode_enabled: bool = True
    # Force fake-provider mode during perf runs for reproducibility.
    perf_fake_provider_mode: bool = True
    # Gate threshold for /v1/run p95 latency in deterministic mode.
    perf_run_target_p95_ms: int = 1800
    # Gate threshold for aggregate workload error-rate.
    perf_max_error_rate: float = 0.02
    # Default soak duration for perf scripts.
    perf_soak_duration_min: int = 15
    # Output directory for perf report artifacts.
    perf_report_dir: str = "tests/perf/reports"
    # Toggle SLA policy evaluation and runtime enforcement features.
    sla_engine_enabled: bool = True
    # Default enforcement mode used when a tenant policy is missing/invalid.
    sla_default_enforcement_mode: str = "observe"
    # Number of breached windows required before enforce actions trigger.
    sla_default_breach_windows: int = 3
    # Primary measurement cadence for SLA signal aggregation.
    sla_measurement_window_seconds: int = 60
    # Rolling window used for error budget burn calculations.
    sla_error_budget_window_minutes: int = 60
    # Allow explicit load shedding responses when sustained breaches occur.
    sla_shed_enabled: bool = True
    # Apply audio-disable mitigation first in SLA degrade mode when enabled.
    sla_degrade_tts_disable: bool = True
    # Floor top_k during SLA degrade mode to reduce retrieval load.
    sla_degrade_top_k_floor: int = 3
    # Cap output tokens during SLA degrade mode to bound generation latency.
    sla_degrade_max_output_tokens: int = 512
    # Toggle autoscaling recommendation/apply control plane.
    autoscaling_enabled: bool = True
    # Keep autoscaling in non-mutating mode unless explicitly disabled.
    autoscaling_dry_run: bool = True
    # Background autoscaling recommendation interval.
    autoscaling_eval_interval_seconds: int = 30
    # Percent hysteresis applied to scaling targets to avoid oscillation.
    autoscaling_hysteresis_pct: int = 10
    # Executor backend for autoscaling apply operations.
    autoscaling_executor: str = "noop"
    # Enable deterministic alert-rule evaluation from ops and admin workflows.
    alerting_enabled: bool = True
    # Enable the periodic evaluator loop that runs alerts/incidents independent of request traffic.
    operability_background_evaluator_enabled: bool = True
    # Poll interval for the background evaluator loop.
    operability_eval_interval_s: int = 30
    # Lock TTL to ensure at most one evaluator loop instance executes at a time.
    operability_eval_lock_ttl_s: int = 55
    # Heartbeat stale threshold for evaluator worker observability.
    operability_worker_heartbeat_stale_after_s: int = 120
    # Enable automatic incident creation and lifecycle automation from alert triggers.
    incident_automation_enabled: bool = True
    # Minimum severity that auto-opens incidents when alerts trigger.
    incident_auto_open_min_severity: str = "high"
    # Notification adapter for alert/incident hooks (noop or webhook).
    ops_notification_adapter: str = "noop"
    # Optional webhook URL used when ops_notification_adapter=webhook.
    ops_notification_webhook_url: str | None = None
    # JSON list of webhook destinations for incident/alert notifications.
    notify_webhook_urls_json: str = "[]"
    # Max notification delivery attempts before jobs are marked gave_up.
    notify_max_attempts: int = 5
    # Base retry backoff in milliseconds for notification jobs.
    notify_backoff_ms: int = 500
    # Upper cap for notification retry backoff in milliseconds.
    notify_backoff_max_ms: int = 15_000
    # Dedupe interval window in seconds for incident notification fan-out.
    notify_dedupe_window_s: int = 300
    # ARQ queue name for durable notification delivery jobs.
    notify_queue_name: str = "notifications"
    # Poll interval for due-job requeue scheduler in the notification worker.
    notify_worker_poll_interval_s: int = 2
    # Batch size for due notification job requeue scans.
    notify_requeue_batch_size: int = 100
    # Default TTL for forced operator control flags to avoid stale cross-region state.
    ops_forced_flag_ttl_s: int = 900
    # Lease TTL for forced-control writers so only one region writer process updates flags at a time.
    ops_forced_writer_lease_ttl_s: int = 30
    # Require a recent worker heartbeat for preflight success when enabled.
    preflight_require_worker_heartbeat: bool = False
    # Directory for GA readiness checklist artifacts.
    ga_checklist_output_dir: str = "var/ops"
    # Enable request-level segment timings for perf diagnostics.
    instrumentation_detailed_timers: bool = True
    # SQLAlchemy async pool size for API runtime database usage.
    api_db_pool_size: int = 20
    # SQLAlchemy overflow connections allowed above pool size.
    api_db_max_overflow: int = 10
    # Postgres statement timeout to bound slow query impact.
    api_db_statement_timeout_ms: int = 15000
    # Explicit /run bulkhead limit (falls back to run_max_concurrency).
    run_bulkhead_max_concurrency: int | None = None
    # Explicit ingest bulkhead limit (falls back to ingest_max_concurrency).
    ingest_bulkhead_max_concurrency: int | None = None
    # Minimum flush cadence for SSE stream frames.
    sse_flush_interval_ms: int = 20
    # Centralize external call timeouts for integrations (ms).
    ext_call_timeout_ms: int = 8000
    # Retry transient integration failures for a bounded number of attempts.
    ext_retry_max_attempts: int = 2
    # Base backoff between retry attempts (ms), jittered per call.
    ext_retry_backoff_ms: int = 200
    # Circuit breaker thresholds for external integrations.
    cb_failure_threshold: int = 5
    cb_open_seconds: int = 30
    cb_half_open_trials: int = 2
    # Prefix circuit breaker keys to isolate environments.
    cb_redis_prefix: str = "nexusrag:cb"
    # Cap concurrent expensive operations to protect core capacity.
    run_max_concurrency: int = 10
    ingest_max_concurrency: int = 4
    # Runtime kill switches to disable features during incidents.
    kill_run: bool = False
    kill_ingest: bool = False
    kill_tts: bool = False
    kill_external_retrieval: bool = False
    # Pause notification enqueue/delivery when incident response needs to stop outbound storms.
    kill_notifications: bool = False
    # Percentage rollouts for gated features (0-100).
    rollout_tts_pct: int = 100
    rollout_external_retrieval_pct: int = 100
    # Prefix rollout keys stored in Redis.
    rollout_redis_prefix: str = "nexusrag:rollout"
    # SLO targets and latency thresholds for ops visibility.
    slo_availability_target: float = 99.9
    slo_p95_run_ms: int = 3000
    slo_p95_api_ms: int = 800
    # Retention window for audit event pruning.
    audit_retention_days: int = 90
    # Retention window for UI action cleanup.
    ui_action_retention_days: int = 30
    # Retention window for usage counter pruning/rollup.
    usage_counter_retention_days: int = 120
    # Limit the number of active self-serve API keys per tenant.
    self_serve_max_active_keys: int = 20
    # Default inactivity threshold used by API key hygiene reports.
    auth_api_key_inactive_days: int = 90
    # Enforce stale API key denial before rate-limit/quota pipelines when enabled.
    auth_api_key_inactive_enforced: bool = True
    # Enable idempotency key support for write endpoints.
    idempotency_enabled: bool = True
    # Control TTL for stored idempotency responses.
    idempotency_ttl_hours: int = 24
    # Toggle automated backups for DR readiness.
    backup_enabled: bool = True
    # Encrypt backup artifacts at rest when enabled.
    backup_encryption_enabled: bool = True
    # Provide a base64/hex encoded backup encryption key.
    backup_encryption_key: str | None = None
    # Sign backup manifests to detect tampering.
    backup_signing_enabled: bool = True
    # Provide an HMAC key for manifest signing.
    backup_signing_key: str | None = None
    # Retain backups for a bounded number of days.
    backup_retention_days: int = 30
    # Cron expression used by external schedulers for backups.
    backup_schedule_cron: str = "0 2 * * *"
    # Verify artifacts immediately after creation when enabled.
    backup_verify_on_create: bool = True
    # Bound parallel uploads to object storage targets.
    backup_max_parallel_uploads: int = 2
    # Local filesystem backup target for development.
    backup_local_dir: str = "./backups"
    # Require valid signatures for restore operations.
    restore_require_signature: bool = True
    # Enable policy-as-code checks for governance decisions.
    governance_policy_engine_enabled: bool = True
    # Local path for DSAR export artifacts and retention reports.
    governance_artifact_dir: str = "./governance_artifacts"
    # Cap evidence query windows to keep ops requests bounded.
    governance_evidence_max_window_days: int = 90
    # Enable SOC 2 compliance automation workflows.
    compliance_enabled: bool = True
    # Default evaluation window for compliance checks.
    compliance_default_window_days: int = 30
    # Cron expression for scheduled compliance evaluations.
    compliance_eval_cron: str = "0 3 * * *"
    # Cron expression for scheduled compliance bundle generation.
    compliance_bundle_cron: str = "0 4 * * 1"
    # Retain compliance evidence bundles for a bounded number of days.
    compliance_evidence_retention_days: int = 365
    # Fail the evaluation pipeline when critical controls fail if enabled.
    compliance_fail_on_critical: bool = False
    # Require signatures for evidence bundles by default.
    compliance_signature_required: bool = True
    # Local filesystem directory for evidence bundle artifacts.
    compliance_evidence_dir: str = "var/evidence"
    # Master key used to encrypt platform keyring material at rest.
    keyring_master_key: str | None = None
    # Require an explicit keyring master key unless local/dev explicitly disables this guardrail.
    keyring_master_key_required: bool = True
    # Enable envelope encryption for sensitive artifacts at rest.
    crypto_enabled: bool = True
    # Select the KMS backend used for tenant key operations.
    crypto_provider: str = "local_kms"
    # Select the payload encryption algorithm (fixed for now).
    crypto_encryption_algo: str = "aes256gcm"
    # Enforce encryption for sensitive writes when enabled.
    crypto_require_encryption_for_sensitive: bool = True
    # Default key alias for per-tenant KEK versions.
    crypto_default_key_alias: str = "tenant-master"
    # Rotation cadence for tenant keys.
    crypto_rotation_interval_days: int = 90
    # Batch size for re-encryption jobs.
    crypto_reencrypt_batch_size: int = 200
    # Limit concurrent re-encryption operations per tenant.
    crypto_max_concurrent_reencrypt: int = 2
    # Choose fail-closed or fail-open behavior when KMS is unavailable.
    crypto_fail_mode: str = "closed"
    # Toggle extra audit metadata for crypto operations.
    crypto_audit_verbose: bool = False
    # Local KMS master key (base64/hex) for deterministic dev/test wraps.
    crypto_local_master_key: str | None = None
    # Identify the local region for failover-aware routing and control-plane decisions.
    region_id: str = "ap-southeast-1"
    # Configure whether this region starts as primary or standby.
    region_role: str = "primary"
    # Toggle multi-region failover controls.
    failover_enabled: bool = True
    # Select manual (token-gated) or assisted failover mode.
    failover_mode: str = "manual"
    # Maximum acceptable replication lag before promotion is blocked.
    replication_lag_max_seconds: int = 30
    # Require healthy replication to allow promotions.
    replication_health_required: bool = True
    # Freeze writes automatically when replication becomes unhealthy.
    write_freeze_on_unhealthy_replica: bool = True
    # Enforce cooldown between failover transitions.
    failover_cooldown_seconds: int = 600
    # Keep approval tokens short-lived for operator safety.
    failover_token_ttl_seconds: int = 300
    # Tie-breaker priority for assisted arbitration decisions.
    region_priority: int = 100
    # JSON list of peer regions used for arbitration signals.
    peer_regions_json: str = "[]"
    # Prefix for failover keys stored in Redis.
    failover_redis_prefix: str = "nexusrag:failover"
    # Sign UI cursor tokens to prevent tampering across pagination requests.
    ui_cursor_secret: str = "dev-ui-cursor-secret"
    # Emit SSE heartbeat events every N seconds for long-running /run streams.
    run_sse_heartbeat_s: int = 10

    google_cloud_project: str | None = None
    google_cloud_location: str | None = None
    gemini_model: str = "gemini-2.0-flash-001"
    # Streaming timeout avoids hanging connections if the provider stalls.
    vertex_stream_timeout_s: int = 90
    # Toggle verbose SSE debug events without changing the API surface.
    debug_events: bool = False
    # Select the LLM provider for dev/test (vertex or fake).
    llm_provider: str = "vertex"

    # TTS provider selection: none/openai/fake for local development.
    tts_provider: str = "none"
    openai_api_key: str | None = None
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    # Base URL used to build audio URLs in SSE payloads.
    audio_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
