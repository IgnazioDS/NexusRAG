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
    String,
    Text,
    func,
    Index,
    UniqueConstraint,
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
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
Index("ix_quota_soft_cap_events_tenant", QuotaSoftCapEvent.tenant_id)
Index("ix_plans_active", Plan.is_active)
Index("ix_plan_features_plan_id", PlanFeature.plan_id)
Index("ix_tenant_plan_assignments_tenant", TenantPlanAssignment.tenant_id)
Index("ix_tenant_plan_assignments_active", TenantPlanAssignment.tenant_id, TenantPlanAssignment.is_active)
Index("ix_tenant_feature_overrides_tenant", TenantFeatureOverride.tenant_id)
Index("ix_plan_upgrade_requests_tenant", PlanUpgradeRequest.tenant_id)
