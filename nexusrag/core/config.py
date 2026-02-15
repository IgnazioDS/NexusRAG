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
    compliance_evidence_dir: str = "./evidence"
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
