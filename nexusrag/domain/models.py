from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from nexusrag.core.config import EMBED_DIM

class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    # Store optional identity hints without making them required for bootstrap flows.
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    # Persist RBAC role as a simple string for fast lookup and migration safety.
    role: Mapped[str] = mapped_column(String)
    # Gate access for disabled users without deleting historical keys.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    # Keep a short prefix for operator display without exposing the secret.
    key_prefix: Mapped[str] = mapped_column(String)
    # Store only the hashed key to avoid plaintext credentials at rest.
    key_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    # Optional label for key management scripts and auditing.
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Enforce optional key expiry for least-privilege and periodic credential rotation.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdentityProvider(Base):
    __tablename__ = "identity_providers"
    __table_args__ = (
        Index("ix_identity_providers_tenant_enabled", "tenant_id", "enabled"),
    )

    # Store tenant-scoped IdP configurations without persisting client secrets.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    # Support both OIDC and future SAML integrations via a stable type field.
    type: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    issuer: Mapped[str] = mapped_column(String)
    client_id: Mapped[str] = mapped_column(String)
    # Store only a secret reference for external resolution (no plaintext).
    client_secret_ref: Mapped[str] = mapped_column(String)
    auth_url: Mapped[str] = mapped_column(String)
    token_url: Mapped[str] = mapped_column(String)
    jwks_url: Mapped[str] = mapped_column(String)
    scopes_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_role: Mapped[str] = mapped_column(String)
    role_mapping_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    jit_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantUser(Base):
    __tablename__ = "tenant_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_subject", name="uq_tenant_users_subject"),
        Index("ix_tenant_users_tenant_email", "tenant_id", "email"),
        Index("ix_tenant_users_tenant_role", "tenant_id", "role"),
    )

    # Represent tenant-bound human identities for SSO and SCIM provisioning flows.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    external_subject: Mapped[str] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Track lifecycle state for SSO and SCIM to avoid hard deletes.
    status: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScimIdentity(Base):
    __tablename__ = "scim_identities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_scim_identities_external"),
    )

    # Map SCIM external identifiers to tenant user records for provisioning syncs.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    external_id: Mapped[str] = mapped_column(String)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("tenant_users.id"), index=True)
    provider_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("identity_providers.id"), nullable=True
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ScimGroup(Base):
    __tablename__ = "scim_groups"

    # Track SCIM groups for role binding and membership reconciliation.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    external_id: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    role_binding: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScimGroupMembership(Base):
    __tablename__ = "scim_group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_scim_group_memberships"),
    )

    # Normalize group membership updates from SCIM into a join table.
    group_id: Mapped[str] = mapped_column(String, ForeignKey("scim_groups.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("tenant_users.id"), primary_key=True)


class ScimToken(Base):
    __tablename__ = "scim_tokens"
    __table_args__ = (
        Index("ix_scim_tokens_tenant", "tenant_id"),
    )

    # Store hashed SCIM bearer tokens separately from API keys.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    token_prefix: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SsoSession(Base):
    __tablename__ = "sso_sessions"
    __table_args__ = (
        Index("ix_sso_sessions_tenant", "tenant_id"),
    )

    # Persist hashed SSO session tokens for revocation and auditing.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("tenant_users.id"), index=True)
    provider_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("identity_providers.id"), nullable=True
    )
    token_prefix: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    # Use a monotonic numeric id for efficient pagination and ordering.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Store the event timestamp separately from creation to preserve source clocks.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Allow null tenant_id for pre-auth or system events.
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    # Capture the actor identity for audit trails across auth types.
    actor_type: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String, nullable=True)
    # Persist a stable event taxonomy for investigation queries.
    event_type: Mapped[str] = mapped_column(String, index=True)
    outcome: Mapped[str] = mapped_column(String)
    resource_type: Mapped[str | None] = mapped_column(String, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Store request identifiers to connect API calls to audit entries.
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    # Keep metadata sanitized and JSONB for flexible investigation.
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanLimit(Base):
    __tablename__ = "plan_limits"

    # Track per-tenant quota limits for billing and abuse protection.
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    daily_requests_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_requests_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Placeholder token quotas for future LLM usage accounting.
    daily_tokens_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_tokens_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Default soft cap ratio allows warnings before hard enforcement.
    soft_cap_ratio: Mapped[float] = mapped_column(Float, default=0.8)
    # Toggle hard cap enforcement for overage observation modes.
    hard_cap_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageCounter(Base):
    __tablename__ = "usage_counters"

    # Track per-tenant usage counts within day/month boundaries.
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    period_type: Mapped[str] = mapped_column(String, primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    requests_count: Mapped[int] = mapped_column(Integer, default=0)
    # Placeholder for future token metering support.
    estimated_tokens_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuotaSoftCapEvent(Base):
    __tablename__ = "quota_soft_cap_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "period_type",
            "period_start",
            "metric",
            name="uq_quota_soft_cap_events_scope",
        ),
    )

    # Deduplicate soft cap alerts per tenant/period/metric.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    period_type: Mapped[str] = mapped_column(String)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metric: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageCostEvent(Base):
    __tablename__ = "usage_cost_events"

    # Record per-request cost events for budgeting and chargeback visibility.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    request_id: Mapped[str | None] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    route_class: Mapped[str] = mapped_column(String)
    component: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    units_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    unit_cost_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class TenantBudget(Base):
    __tablename__ = "tenant_budgets"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_budgets_tenant"),
    )

    # Store monthly budget policy per tenant with warn/cap settings.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    monthly_budget_usd: Mapped[float] = mapped_column(Numeric(12, 2))
    warn_ratio: Mapped[float] = mapped_column(Numeric(5, 4), default=0.8)
    enforce_hard_cap: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hard_cap_mode: Mapped[str] = mapped_column(String, default="block")
    current_month_override_usd: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TenantBudgetSnapshot(Base):
    __tablename__ = "tenant_budget_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "year_month", name="uq_budget_snapshots_month"),
    )

    # Capture monthly spend snapshots for budget enforcement and reporting.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    year_month: Mapped[str] = mapped_column(String(length=7))
    budget_usd: Mapped[float] = mapped_column(Numeric(12, 2))
    spend_usd: Mapped[float] = mapped_column(Numeric(12, 6))
    forecast_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    warn_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cap_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PricingCatalog(Base):
    __tablename__ = "pricing_catalog"

    # Store pricing catalog entries for deterministic cost calculations.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String)
    component: Mapped[str] = mapped_column(String)
    rate_type: Mapped[str] = mapped_column(String)
    rate_value_usd: Mapped[float] = mapped_column(Numeric(12, 6))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class ChargebackReport(Base):
    __tablename__ = "chargeback_reports"

    # Snapshot chargeback totals for reporting and reconciliation.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String, default="USD")
    total_usd: Mapped[float] = mapped_column(Numeric(12, 6))
    breakdown_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    generated_by: Mapped[str | None] = mapped_column(String, nullable=True)


class SlaPolicy(Base):
    __tablename__ = "sla_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "version", name="uq_sla_policies_tenant_name_version"),
    )

    # Version tenant/global SLA policy documents to keep enforcement deterministic.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String)
    tier: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantSlaAssignment(Base):
    __tablename__ = "tenant_sla_assignments"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_sla_assignments_tenant"),
    )

    # Bind one active SLA policy per tenant with optional temporary overrides.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    policy_id: Mapped[str] = mapped_column(String, ForeignKey("sla_policies.id"), index=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    override_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SlaMeasurement(Base):
    __tablename__ = "sla_measurements"
    __table_args__ = (
        Index("ix_sla_measurements_tenant_route_window_end", "tenant_id", "route_class", "window_end"),
    )

    # Persist rolling route-class SLA windows for runtime decisions and trends.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    route_class: Mapped[str] = mapped_column(String, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_count: Mapped[int] = mapped_column(Integer)
    error_count: Mapped[int] = mapped_column(Integer)
    p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p99_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    availability_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    saturation_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SlaIncident(Base):
    __tablename__ = "sla_incidents"

    # Track breach lifecycle and mitigation status for operator workflows.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    policy_id: Mapped[str] = mapped_column(String, ForeignKey("sla_policies.id"), index=True)
    route_class: Mapped[str] = mapped_column(String)
    breach_type: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    first_breach_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_breach_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutoscalingProfile(Base):
    __tablename__ = "autoscaling_profiles"
    __table_args__ = (
        Index("ix_autoscaling_profiles_tenant", "tenant_id"),
    )

    # Define autoscaling bounds and control-loop targets for recommendations.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    route_class: Mapped[str | None] = mapped_column(String, nullable=True)
    min_replicas: Mapped[int] = mapped_column(Integer)
    max_replicas: Mapped[int] = mapped_column(Integer)
    target_p95_ms: Mapped[int] = mapped_column(Integer)
    target_queue_depth: Mapped[int] = mapped_column(Integer)
    cooldown_seconds: Mapped[int] = mapped_column(Integer)
    step_up: Mapped[int] = mapped_column(Integer)
    step_down: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AutoscalingAction(Base):
    __tablename__ = "autoscaling_actions"
    __table_args__ = (
        Index("ix_autoscaling_actions_tenant", "tenant_id"),
    )

    # Persist autoscaling recommendations/applies to preserve full control-plane audit trails.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String, ForeignKey("autoscaling_profiles.id"), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    route_class: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    from_replicas: Mapped[int] = mapped_column(Integer)
    to_replicas: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    signal_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    executed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Plan(Base):
    __tablename__ = "plans"

    # Store plan catalog entries for entitlement assignments and enforcement.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanFeature(Base):
    __tablename__ = "plan_features"

    # Map plan-level entitlements with optional per-feature configuration.
    plan_id: Mapped[str] = mapped_column(String, ForeignKey("plans.id"), primary_key=True)
    feature_key: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantPlanAssignment(Base):
    __tablename__ = "tenant_plan_assignments"

    # Track tenant plan history while enforcing a single active assignment.
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String, ForeignKey("plans.id"), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantFeatureOverride(Base):
    __tablename__ = "tenant_feature_overrides"

    # Allow tenant-specific overrides to supersede plan entitlements.
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    feature_key: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanUpgradeRequest(Base):
    __tablename__ = "plan_upgrade_requests"

    # Track tenant-initiated plan upgrade requests for review workflows.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    current_plan_id: Mapped[str] = mapped_column(String)
    target_plan_id: Mapped[str] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String)
    requested_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BackupJob(Base):
    __tablename__ = "backup_jobs"
    __table_args__ = (
        Index("ix_backup_jobs_status", "status"),
        Index("ix_backup_jobs_started_at", "started_at"),
    )

    # Track DR backup lifecycle for readiness and audit reporting.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_scope: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    manifest_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class RestoreDrill(Base):
    __tablename__ = "restore_drills"
    __table_args__ = (
        Index("ix_restore_drills_status", "status"),
        Index("ix_restore_drills_started_at", "started_at"),
    )

    # Persist restore drill results for compliance evidence.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    rto_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verified_manifest_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class FailoverClusterState(Base):
    __tablename__ = "failover_cluster_state"

    # Persist active primary and write-freeze state for Redis loss recovery.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_primary_region: Mapped[str] = mapped_column(String, index=True)
    epoch: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_transition_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freeze_writes: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RegionStatus(Base):
    __tablename__ = "region_status"
    __table_args__ = (
        Index("ix_region_status_health_updated", "health_status", "updated_at"),
    )

    # Track per-region role/health for readiness arbitration.
    region_id: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    health_status: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    replication_lag_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    writable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FailoverEvent(Base):
    __tablename__ = "failover_events"
    __table_args__ = (
        Index("ix_failover_events_status_started", "status", "started_at"),
    )

    # Persist failover attempts and outcomes for operator auditability.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    from_region: Mapped[str | None] = mapped_column(String, nullable=True)
    to_region: Mapped[str | None] = mapped_column(String, nullable=True)
    mode: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approval_token_id: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class FailoverToken(Base):
    __tablename__ = "failover_tokens"
    __table_args__ = (
        Index("ix_failover_tokens_expires_at", "expires_at"),
    )

    # Store one-time approval tokens as hashes to avoid plaintext persistence.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    requested_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    purpose: Mapped[str] = mapped_column(String, nullable=False)


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    # Keep tenant-scoped retention settings explicit for governance enforcement.
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    messages_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checkpoints_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audit_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    documents_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backups_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Hard delete remains opt-in so tenants can start with safer anonymization.
    hard_delete_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Default to anonymization for privacy-by-default behavior.
    anonymize_instead_of_delete: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LegalHold(Base):
    __tablename__ = "legal_holds"

    # Track hold scopes so deletion pipelines can defer destructive actions.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    scope_type: Mapped[str] = mapped_column(String, index=True)
    scope_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    created_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DsarRequest(Base):
    __tablename__ = "dsar_requests"

    # Persist DSAR job lifecycles and evidence links for compliance audits.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    request_type: Mapped[str] = mapped_column(String)
    subject_type: Mapped[str] = mapped_column(String)
    subject_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    requested_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    # Support tenant/global policy-as-code rules with deterministic precedence.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    rule_key: Mapped[str] = mapped_column(String, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False, index=True)
    condition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    action_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthorizationPolicy(Base):
    __tablename__ = "authorization_policies"
    __table_args__ = (
        Index(
            "ix_authz_policies_tenant_enabled_resource_action_priority",
            "tenant_id",
            "enabled",
            "resource_type",
            "action",
            text("priority DESC"),
        ),
    )

    # Store ABAC policies with tenant scoping and deterministic precedence.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    effect: Mapped[str] = mapped_column(String)
    resource_type: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    condition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GovernanceRetentionRun(Base):
    __tablename__ = "governance_retention_runs"

    # Keep retention execution reports queryable for compliance evidence endpoints.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)


class TenantKey(Base):
    __tablename__ = "tenant_keys"
    __table_args__ = (
        Index("ix_tenant_keys_tenant_status_version", "tenant_id", "status", text("key_version DESC")),
        UniqueConstraint("tenant_id", "key_alias", "key_version", name="uq_tenant_keys_version"),
    )

    # Track tenant-scoped KEK versions for envelope encryption.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    key_alias: Mapped[str] = mapped_column(String)
    key_version: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String)
    key_ref: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class EncryptedBlob(Base):
    __tablename__ = "encrypted_blobs"
    __table_args__ = (
        Index("ix_encrypted_blobs_tenant_resource", "tenant_id", "resource_type", "resource_id"),
    )

    # Store encrypted payloads with envelope-encryption metadata.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    resource_type: Mapped[str] = mapped_column(String, index=True)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    key_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tenant_keys.id"))
    wrapped_dek: Mapped[str] = mapped_column(Text)
    nonce: Mapped[str] = mapped_column(Text)
    tag: Mapped[str] = mapped_column(Text)
    cipher_text: Mapped[str] = mapped_column(Text)
    aad_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum_sha256: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KeyRotationJob(Base):
    __tablename__ = "key_rotation_jobs"
    __table_args__ = (
        Index("ix_key_rotation_jobs_tenant_status_created", "tenant_id", "status", text("created_at DESC")),
    )

    # Track key rotation and re-encryption progress for auditing.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    from_key_id: Mapped[int] = mapped_column(BigInteger)
    to_key_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String, index=True)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformKey(Base):
    __tablename__ = "platform_keys"
    __table_args__ = (
        Index("ix_platform_keys_purpose_status_created", "purpose", "status", text("created_at DESC")),
    )

    # Track platform-level signing/encryption key lifecycle independently from tenant data keys.
    key_id: Mapped[str] = mapped_column(String, primary_key=True)
    purpose: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    # Store encrypted key material to avoid plaintext secrets at rest.
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ControlCatalog(Base):
    __tablename__ = "control_catalog"

    # Define SOC 2 control metadata used by automated evaluations.
    control_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    trust_criteria: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(Text)
    owner_role: Mapped[str] = mapped_column(String)
    check_type: Mapped[str] = mapped_column(String)
    frequency: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    severity: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ControlMapping(Base):
    __tablename__ = "control_mappings"

    # Map SOC 2 controls to measurable platform signals and evidence templates.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    control_id: Mapped[str] = mapped_column(String, ForeignKey("control_catalog.control_id"), index=True)
    signal_type: Mapped[str] = mapped_column(String)
    signal_ref: Mapped[str] = mapped_column(String)
    condition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_template_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ControlEvaluation(Base):
    __tablename__ = "control_evaluations"
    __table_args__ = (
        Index("ix_control_evaluations_control_eval", "control_id", text("evaluated_at DESC")),
        Index("ix_control_evaluations_status_eval", "status", text("evaluated_at DESC")),
    )

    # Store periodic control evaluations for SOC 2 reporting.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    control_id: Mapped[str] = mapped_column(String, ForeignKey("control_catalog.control_id"), index=True)
    tenant_scope: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    findings_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    evidence_refs_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceBundle(Base):
    __tablename__ = "evidence_bundles"
    __table_args__ = (
        Index("ix_evidence_bundles_status_generated", "status", text("generated_at DESC")),
    )

    # Track SOC 2 evidence bundle generation and verification.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bundle_type: Mapped[str] = mapped_column(String)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, index=True)
    manifest_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    signature: Mapped[str | None] = mapped_column(String, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class ComplianceArtifact(Base):
    __tablename__ = "compliance_artifacts"
    __table_args__ = (
        Index("ix_compliance_artifacts_type_created", "artifact_type", text("created_at DESC")),
    )

    # Store manual evidence artifacts such as dependency scan attestations.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    artifact_type: Mapped[str] = mapped_column(String, index=True)
    control_id: Mapped[str | None] = mapped_column(String, ForeignKey("control_catalog.control_id"), nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class ComplianceSnapshot(Base):
    __tablename__ = "compliance_snapshots"
    __table_args__ = (
        Index("ix_compliance_snapshots_created", text("created_at DESC")),
    )

    # Persist point-in-time control evaluations and redacted evidence metadata for audit exports.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    controls_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class RetentionRun(Base):
    __tablename__ = "retention_runs"
    __table_args__ = (
        Index("ix_retention_runs_task_last_run", "task", text("last_run_at DESC")),
    )

    # Record retention maintenance executions for externally verifiable governance posture.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    task: Mapped[str] = mapped_column(String, index=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    outcome: Mapped[str] = mapped_column(String)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "actor_id",
            "method",
            "path",
            "idem_key",
            name="uq_idempotency_records_scope",
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    # Store request/response snapshots to enable safe idempotent retries.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    actor_id: Mapped[str] = mapped_column(String, index=True)
    method: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    idem_key: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    response_status: Mapped[int] = mapped_column(Integer)
    response_body_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UiAction(Base):
    __tablename__ = "ui_actions"

    # Persist optimistic UI actions to support frontend polling and reconciliation.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    actor_id: Mapped[str] = mapped_column(String, index=True)
    action_type: Mapped[str] = mapped_column(String, index=True)
    request_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, index=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("sessions.id"), index=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Corpus(Base):
    __tablename__ = "corpora"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    provider_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    corpus_id: Mapped[str] = mapped_column(String, index=True)
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    # Preserve the original source field for compatibility; align value with ingest_source.
    source: Mapped[str] = mapped_column(String, default="upload_file")
    # Track ingestion origin explicitly for lifecycle endpoints.
    ingest_source: Mapped[str] = mapped_column(String, default="upload_file")
    # Store a local path for reindexing; production will move to object storage.
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # Capture user-provided metadata for reuse on reindex.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, index=True)
    # Preserve legacy error_message for compatibility; new APIs use failure_reason.
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    # Store short, actionable failure descriptions for async ingestion status.
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Capture when the document entered the queue for observability.
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Capture when the worker started processing for SLA tracking.
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Capture when ingestion finished (success or failure).
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Store the last ingestion job id for tracing.
    last_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Track ingestion state transitions without relying on app clocks.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Capture the last time content was reindexed for operational visibility.
    last_reindexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentPermission(Base):
    __tablename__ = "document_permissions"
    __table_args__ = (
        Index("ix_doc_permissions_tenant_document", "tenant_id", "document_id"),
        Index("ix_doc_permissions_tenant_principal", "tenant_id", "principal_type", "principal_id"),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "principal_type",
            "principal_id",
            "permission",
            name="uq_doc_permissions_principal_permission",
        ),
    )

    # Record explicit document-level grants for principals.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), index=True)
    principal_type: Mapped[str] = mapped_column(String)
    principal_id: Mapped[str] = mapped_column(String)
    permission: Mapped[str] = mapped_column(String)
    granted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentLabel(Base):
    __tablename__ = "document_labels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "document_id", "key", name="uq_document_labels_key"),
    )

    # Capture document labels for ABAC policy evaluation.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), index=True)
    key: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String)


class PrincipalAttribute(Base):
    __tablename__ = "principal_attributes"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "principal_type",
            "principal_id",
            name="uq_principal_attributes_identity",
        ),
    )

    # Cache computed principal attributes for ABAC evaluation.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    principal_type: Mapped[str] = mapped_column(String)
    principal_id: Mapped[str] = mapped_column(String)
    attrs_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    corpus_id: Mapped[str] = mapped_column(String, index=True)
    document_id: Mapped[str | None] = mapped_column(String, ForeignKey("documents.id"), nullable=True)
    document_uri: Mapped[str] = mapped_column(String)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # Keep vector dimension aligned with embedding generation and retrieval.
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_chunks_corpus_id", Chunk.corpus_id)
Index("ix_documents_status_queued_at", Document.status, Document.queued_at.desc())
Index("ix_documents_status_processing_started_at", Document.status, Document.processing_started_at.desc())
Index("ix_documents_status_completed_at", Document.status, Document.completed_at.desc())
Index("ix_api_keys_expires_at", ApiKey.expires_at)
Index(
    "ix_audit_events_tenant_occurred_at",
    AuditEvent.tenant_id,
    AuditEvent.occurred_at.desc(),
)
Index(
    "ix_audit_events_event_type_occurred_at",
    AuditEvent.event_type,
    AuditEvent.occurred_at.desc(),
)
Index(
    "ix_audit_events_outcome_occurred_at",
    AuditEvent.outcome,
    AuditEvent.occurred_at.desc(),
)
Index("ix_plan_limits_tenant_id", PlanLimit.tenant_id)
Index(
    "ix_usage_counters_tenant_period",
    UsageCounter.tenant_id,
    UsageCounter.period_type,
    UsageCounter.period_start,
)
Index("ix_usage_cost_events_tenant_occurred", UsageCostEvent.tenant_id, UsageCostEvent.occurred_at)
Index(
    "ix_usage_cost_events_component",
    UsageCostEvent.tenant_id,
    UsageCostEvent.component,
    UsageCostEvent.occurred_at,
)
Index("ix_tenant_budgets_tenant", TenantBudget.tenant_id)
Index("ix_tenant_budget_snapshots_tenant", TenantBudgetSnapshot.tenant_id)
Index("ix_pricing_catalog_version", PricingCatalog.version)
Index(
    "ix_pricing_catalog_provider_component_active",
    PricingCatalog.provider,
    PricingCatalog.component,
    PricingCatalog.active,
)
Index("ix_chargeback_reports_tenant", ChargebackReport.tenant_id)
Index("ix_quota_soft_cap_events_tenant", QuotaSoftCapEvent.tenant_id)
Index("ix_plans_active", Plan.is_active)
Index("ix_plan_features_plan_id", PlanFeature.plan_id)
Index("ix_tenant_plan_assignments_tenant", TenantPlanAssignment.tenant_id)
Index("ix_tenant_plan_assignments_active", TenantPlanAssignment.tenant_id, TenantPlanAssignment.is_active)
Index("ix_tenant_feature_overrides_tenant", TenantFeatureOverride.tenant_id)
Index("ix_plan_upgrade_requests_tenant", PlanUpgradeRequest.tenant_id)
Index("ix_ui_actions_tenant_created_at", UiAction.tenant_id, UiAction.created_at.desc())
Index("ix_ui_actions_status", UiAction.status)
Index("ix_legal_holds_tenant_active", LegalHold.tenant_id, LegalHold.is_active)
Index("ix_legal_holds_scope", LegalHold.scope_type, LegalHold.scope_id)
Index("ix_dsar_requests_tenant_status", DsarRequest.tenant_id, DsarRequest.status)
Index("ix_dsar_requests_created_at", DsarRequest.created_at.desc())
Index("ix_policy_rules_rule_priority", PolicyRule.rule_key, PolicyRule.priority.desc())
Index("ix_governance_retention_runs_tenant_started", GovernanceRetentionRun.tenant_id, GovernanceRetentionRun.started_at.desc())
