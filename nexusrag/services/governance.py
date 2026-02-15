from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import hmac
import json
from pathlib import Path
import shutil
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    ApiKey,
    AuditEvent,
    BackupJob,
    Checkpoint,
    Chunk,
    Corpus,
    Document,
    DsarRequest,
    EncryptedBlob,
    GovernanceRetentionRun,
    KeyRotationJob,
    LegalHold,
    Message,
    PolicyRule,
    RetentionPolicy,
    Session,
    TenantKey,
    User,
)
from nexusrag.services.audit import record_event
from nexusrag.services import backup as backup_service
from nexusrag.services.crypto import CRYPTO_RESOURCE_DSAR, ensure_encryption_available, store_encrypted_blob
from nexusrag.services.policy_engine import PolicyDecision, evaluate_policy, redact_context_fields


LEGAL_HOLD_SCOPE_TENANT = "tenant"
LEGAL_HOLD_SCOPE_DOCUMENT = "document"
LEGAL_HOLD_SCOPE_SESSION = "session"
LEGAL_HOLD_SCOPE_USER_KEY = "user_key"
LEGAL_HOLD_SCOPE_BACKUP_SET = "backup_set"

DSAR_STATUS_PENDING = "pending"
DSAR_STATUS_RUNNING = "running"
DSAR_STATUS_COMPLETED = "completed"
DSAR_STATUS_FAILED = "failed"
DSAR_STATUS_REJECTED = "rejected"


@dataclass(frozen=True)
class GovernanceEvidenceBundle:
    # Return evidence metadata grouped for external audit packaging.
    retention_runs: list[dict[str, Any]]
    dsar_requests: list[dict[str, Any]]
    legal_holds: list[dict[str, Any]]
    policy_changes: list[dict[str, Any]]


def _utc_now() -> datetime:
    # Use UTC for all governance timestamps to avoid timezone ambiguity.
    return datetime.now(timezone.utc)


def _governance_error(code: str, message: str, status_code: int) -> HTTPException:
    # Keep governance errors stable for API clients and audit automation.
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _ensure_artifact_dir() -> Path:
    # Keep DSAR artifacts in a dedicated directory to simplify retention and evidence export.
    settings = get_settings()
    target = Path(settings.governance_artifact_dir)
    target.mkdir(parents=True, exist_ok=True)
    return target


async def get_or_create_retention_policy(session: AsyncSession, tenant_id: str) -> RetentionPolicy:
    # Create default tenant policy lazily to avoid setup-time coupling.
    policy = await session.get(RetentionPolicy, tenant_id)
    if policy is not None:
        return policy
    policy = RetentionPolicy(tenant_id=tenant_id)
    session.add(policy)
    await session.commit()
    await session.refresh(policy)
    return policy


async def list_active_legal_holds(session: AsyncSession, tenant_id: str) -> list[LegalHold]:
    # Filter expired holds out of active enforcement queries.
    now = _utc_now()
    holds = (
        await session.execute(
            select(LegalHold)
            .where(
                LegalHold.tenant_id == tenant_id,
                LegalHold.is_active.is_(True),
                or_(LegalHold.expires_at.is_(None), LegalHold.expires_at > now),
            )
            .order_by(LegalHold.created_at.desc())
        )
    ).scalars().all()
    return list(holds)


def _hold_matches_scope(hold: LegalHold, scope_type: str, scope_id: str | None) -> bool:
    # Tenant holds apply globally; scoped holds match type/id directly.
    if hold.scope_type == LEGAL_HOLD_SCOPE_TENANT:
        return True
    if hold.scope_type != scope_type:
        return False
    if hold.scope_id is None:
        return True
    return hold.scope_id == scope_id


async def find_applicable_legal_hold(
    session: AsyncSession,
    *,
    tenant_id: str,
    scope_type: str,
    scope_id: str | None,
) -> LegalHold | None:
    # Return the newest applicable hold to support clear operator messaging.
    holds = await list_active_legal_holds(session, tenant_id)
    for hold in holds:
        if _hold_matches_scope(hold, scope_type, scope_id):
            return hold
    return None


async def enforce_no_legal_hold(
    session: AsyncSession,
    *,
    tenant_id: str,
    scope_type: str,
    scope_id: str | None,
) -> None:
    # Reject destructive actions when an active legal hold applies.
    hold = await find_applicable_legal_hold(
        session,
        tenant_id=tenant_id,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    if hold is None:
        return
    raise _governance_error("LEGAL_HOLD_ACTIVE", "Operation blocked by active legal hold", 409)


async def enforce_policy(
    *,
    session: AsyncSession,
    tenant_id: str,
    actor_id: str | None,
    actor_role: str | None,
    rule_key: str,
    context: dict[str, Any],
    request_id: str | None,
    allow_require_approval: bool = False,
) -> PolicyDecision:
    # Evaluate policy engine and fail closed when rules deny a request.
    decision = await evaluate_policy(
        session=session,
        tenant_id=tenant_id,
        rule_key=rule_key,
        context=context,
    )
    audit_context = context
    if decision.redact_fields:
        audit_context = redact_context_fields(context, decision.redact_fields)
    if decision.require_approval and not allow_require_approval:
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="governance.policy.denied",
            outcome="failure",
            resource_type="policy_rule",
            resource_id=str(decision.rule_id) if decision.rule_id else None,
            request_id=request_id,
            metadata={**audit_context, "rule_key": rule_key, "action": decision.action},
            error_code="DSAR_REQUIRES_APPROVAL",
            commit=True,
            best_effort=True,
        )
        raise _governance_error(
            "DSAR_REQUIRES_APPROVAL",
            decision.message or "Approval required by governance policy",
            409,
        )
    if decision.require_encryption:
        try:
            ensure_encryption_available()
        except HTTPException as exc:
            await record_event(
                session=session,
                tenant_id=tenant_id,
                actor_type="api_key",
                actor_id=actor_id,
                actor_role=actor_role,
                event_type="crypto.policy.denied",
                outcome="failure",
                resource_type="policy_rule",
                resource_id=str(decision.rule_id) if decision.rule_id else None,
                request_id=request_id,
                metadata={**audit_context, "rule_key": rule_key, "action": decision.action},
                error_code="ENCRYPTION_REQUIRED",
                commit=True,
                best_effort=True,
            )
            raise
    if decision.allowed:
        return decision
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="governance.policy.denied",
        outcome="failure",
        resource_type="policy_rule",
        resource_id=str(decision.rule_id) if decision.rule_id else None,
        request_id=request_id,
        metadata={**audit_context, "rule_key": rule_key, "action": decision.action},
        error_code="POLICY_DENIED",
        commit=True,
        best_effort=True,
    )
    raise _governance_error("POLICY_DENIED", decision.message or "Request denied by governance policy", 403)


def _retention_mode(policy: RetentionPolicy) -> str:
    # Resolve data lifecycle behavior once per run for consistent execution.
    if policy.hard_delete_enabled and not policy.anonymize_instead_of_delete:
        return "hard_delete"
    return "anonymize"


async def _emit_skip_hold_event(
    *,
    session: AsyncSession,
    tenant_id: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
    category: str,
    skipped_count: int,
) -> None:
    # Emit skipped-hold events so retention reports are externally explainable.
    if skipped_count <= 0:
        return
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="governance.retention.item.skipped_hold",
        outcome="success",
        resource_type="governance",
        resource_id=category,
        request_id=request_id,
        metadata={"category": category, "skipped_count": skipped_count},
        commit=True,
        best_effort=True,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sign_payload(payload: bytes) -> str | None:
    # Reuse configured signing key when available to produce tamper-evident artifacts.
    settings = get_settings()
    if not settings.backup_signing_enabled or not settings.backup_signing_key:
        return None
    return hmac.new(
        settings.backup_signing_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


async def run_retention_for_tenant(
    *,
    session: AsyncSession,
    tenant_id: str,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> GovernanceRetentionRun:
    # Execute tenant lifecycle policy and persist an evidence-friendly run report.
    policy = await get_or_create_retention_policy(session, tenant_id)
    mode = _retention_mode(policy)
    run = GovernanceRetentionRun(
        tenant_id=tenant_id,
        status="running",
        started_at=_utc_now(),
        report_json={"mode": mode},
        created_by_actor_id=actor_id,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="governance.retention.run.started",
        outcome="success",
        resource_type="governance_retention_run",
        resource_id=str(run.id),
        request_id=request_id,
        metadata={"mode": mode},
        commit=True,
        best_effort=True,
    )

    holds = await list_active_legal_holds(session, tenant_id)
    tenant_hold = any(hold.scope_type == LEGAL_HOLD_SCOPE_TENANT for hold in holds)
    held_documents = {hold.scope_id for hold in holds if hold.scope_type == LEGAL_HOLD_SCOPE_DOCUMENT and hold.scope_id}
    held_sessions = {hold.scope_id for hold in holds if hold.scope_type == LEGAL_HOLD_SCOPE_SESSION and hold.scope_id}
    held_backup_sets = {hold.scope_id for hold in holds if hold.scope_type == LEGAL_HOLD_SCOPE_BACKUP_SET and hold.scope_id}

    report: dict[str, Any] = {
        "tenant_id": tenant_id,
        "mode": mode,
        "started_at": run.started_at.isoformat(),
        "categories": {},
    }
    try:
        now = _utc_now()
        tenant_session_ids = (
            await session.execute(select(Session.id).where(Session.tenant_id == tenant_id))
        ).scalars().all()
        tenant_session_set = set(tenant_session_ids)

        async def _process_messages() -> dict[str, int]:
            result = {"processed": 0, "deleted": 0, "anonymized": 0, "skipped_hold": 0}
            if policy.messages_ttl_days is None:
                return result
            cutoff = now - timedelta(days=policy.messages_ttl_days)
            rows = (
                await session.execute(
                    select(Message.id, Message.session_id).where(
                        Message.created_at < cutoff,
                        Message.session_id.in_(tenant_session_set),
                    )
                )
            ).all()
            result["processed"] = len(rows)
            if not rows:
                return result
            if tenant_hold:
                result["skipped_hold"] = len(rows)
                return result
            eligible_ids = [message_id for message_id, session_id in rows if session_id not in held_sessions]
            result["skipped_hold"] = len(rows) - len(eligible_ids)
            if not eligible_ids:
                return result
            if mode == "hard_delete":
                deleted = await session.execute(delete(Message).where(Message.id.in_(eligible_ids)))
                result["deleted"] = deleted.rowcount or 0
            else:
                updated = await session.execute(
                    update(Message).where(Message.id.in_(eligible_ids)).values(content="[ANONYMIZED]")
                )
                result["anonymized"] = updated.rowcount or 0
            return result

        async def _process_checkpoints() -> dict[str, int]:
            result = {"processed": 0, "deleted": 0, "anonymized": 0, "skipped_hold": 0}
            if policy.checkpoints_ttl_days is None:
                return result
            cutoff = now - timedelta(days=policy.checkpoints_ttl_days)
            rows = (
                await session.execute(
                    select(Checkpoint.id, Checkpoint.session_id).where(
                        Checkpoint.created_at < cutoff,
                        Checkpoint.session_id.in_(tenant_session_set),
                    )
                )
            ).all()
            result["processed"] = len(rows)
            if not rows:
                return result
            if tenant_hold:
                result["skipped_hold"] = len(rows)
                return result
            eligible_ids = [checkpoint_id for checkpoint_id, session_id in rows if session_id not in held_sessions]
            result["skipped_hold"] = len(rows) - len(eligible_ids)
            if not eligible_ids:
                return result
            if mode == "hard_delete":
                deleted = await session.execute(delete(Checkpoint).where(Checkpoint.id.in_(eligible_ids)))
                result["deleted"] = deleted.rowcount or 0
            else:
                updated = await session.execute(
                    update(Checkpoint)
                    .where(Checkpoint.id.in_(eligible_ids))
                    .values(state_json={"anonymized": True})
                )
                result["anonymized"] = updated.rowcount or 0
            return result

        async def _process_documents() -> dict[str, int]:
            result = {"processed": 0, "deleted": 0, "anonymized": 0, "skipped_hold": 0}
            if policy.documents_ttl_days is None:
                return result
            cutoff = now - timedelta(days=policy.documents_ttl_days)
            rows = (
                await session.execute(
                    select(Document.id).where(
                        Document.tenant_id == tenant_id,
                        Document.created_at < cutoff,
                    )
                )
            ).scalars().all()
            result["processed"] = len(rows)
            if not rows:
                return result
            if tenant_hold:
                result["skipped_hold"] = len(rows)
                return result
            eligible_ids = [document_id for document_id in rows if document_id not in held_documents]
            result["skipped_hold"] = len(rows) - len(eligible_ids)
            if not eligible_ids:
                return result
            if mode == "hard_delete":
                await session.execute(delete(Chunk).where(Chunk.document_id.in_(eligible_ids)))
                deleted = await session.execute(delete(Document).where(Document.id.in_(eligible_ids)))
                result["deleted"] = deleted.rowcount or 0
            else:
                await session.execute(
                    update(Chunk).where(Chunk.document_id.in_(eligible_ids)).values(text="[ANONYMIZED]")
                )
                updated = await session.execute(
                    update(Document)
                    .where(Document.id.in_(eligible_ids))
                    .values(
                        filename="[ANONYMIZED]",
                        content_type="application/octet-stream",
                        storage_path=None,
                        metadata_json={"anonymized": True},
                    )
                )
                result["anonymized"] = updated.rowcount or 0
            return result

        async def _process_audit() -> dict[str, int]:
            result = {"processed": 0, "deleted": 0, "anonymized": 0, "skipped_hold": 0}
            if policy.audit_ttl_days is None:
                return result
            cutoff = now - timedelta(days=policy.audit_ttl_days)
            rows = (
                await session.execute(
                    select(AuditEvent.id).where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.occurred_at < cutoff,
                    )
                )
            ).scalars().all()
            result["processed"] = len(rows)
            if not rows:
                return result
            if tenant_hold:
                result["skipped_hold"] = len(rows)
                return result
            if mode == "hard_delete":
                deleted = await session.execute(delete(AuditEvent).where(AuditEvent.id.in_(rows)))
                result["deleted"] = deleted.rowcount or 0
            else:
                updated = await session.execute(
                    update(AuditEvent)
                    .where(AuditEvent.id.in_(rows))
                    .values(ip_address=None, user_agent=None, metadata_json={"anonymized": True})
                )
                result["anonymized"] = updated.rowcount or 0
            return result

        async def _process_backups() -> dict[str, int]:
            result = {"processed": 0, "deleted": 0, "skipped_hold": 0}
            if policy.backups_ttl_days is None:
                return result
            if tenant_hold:
                return result
            base_dir = Path(get_settings().backup_local_dir)
            cutoff = now - timedelta(days=policy.backups_ttl_days)
            if not base_dir.exists():
                return result
            for manifest_path in base_dir.rglob("manifest.json"):
                try:
                    manifest = backup_service._load_manifest(manifest_path)
                    backup_id = str(manifest.backup_id)
                    created_at = datetime.fromisoformat(str(manifest.created_at))
                except Exception:
                    continue
                if created_at >= cutoff:
                    continue
                result["processed"] += 1
                manifest_uri = str(manifest_path)
                if backup_id in held_backup_sets or manifest_uri in held_backup_sets:
                    result["skipped_hold"] += 1
                    continue
                shutil.rmtree(manifest_path.parent, ignore_errors=True)
                result["deleted"] += 1
                try:
                    job_id = int(backup_id)
                except ValueError:
                    job_id = None
                if job_id is not None:
                    job = await session.get(BackupJob, job_id)
                    if job is not None:
                        job.status = "pruned"
                        job.completed_at = _utc_now()
            return result

        report["categories"]["messages"] = await _process_messages()
        report["categories"]["checkpoints"] = await _process_checkpoints()
        report["categories"]["documents"] = await _process_documents()
        report["categories"]["audit"] = await _process_audit()
        report["categories"]["backups"] = await _process_backups()
        await _emit_skip_hold_event(
            session=session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            category="messages",
            skipped_count=report["categories"]["messages"]["skipped_hold"],
        )
        await _emit_skip_hold_event(
            session=session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            category="checkpoints",
            skipped_count=report["categories"]["checkpoints"]["skipped_hold"],
        )
        await _emit_skip_hold_event(
            session=session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            category="documents",
            skipped_count=report["categories"]["documents"]["skipped_hold"],
        )
        await _emit_skip_hold_event(
            session=session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            category="audit",
            skipped_count=report["categories"]["audit"]["skipped_hold"],
        )
        await _emit_skip_hold_event(
            session=session,
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            request_id=request_id,
            category="backups",
            skipped_count=report["categories"]["backups"]["skipped_hold"],
        )
        run.status = "completed"
        run.completed_at = _utc_now()
        run.report_json = report
        await session.commit()
        await session.refresh(run)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="governance.retention.run.completed",
            outcome="success",
            resource_type="governance_retention_run",
            resource_id=str(run.id),
            request_id=request_id,
            metadata={"report": report},
            commit=True,
            best_effort=True,
        )
        return run
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - retention should emit failure reports.
        run.status = "failed"
        run.completed_at = _utc_now()
        run.error_code = "GOVERNANCE_RETENTION_FAILED"
        run.error_message = str(exc)
        run.report_json = report
        await session.commit()
        await session.refresh(run)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=actor_id,
            actor_role=actor_role,
            event_type="governance.retention.run.failed",
            outcome="failure",
            resource_type="governance_retention_run",
            resource_id=str(run.id),
            request_id=request_id,
            metadata={"report": report},
            error_code="GOVERNANCE_RETENTION_FAILED",
            commit=True,
            best_effort=True,
        )
        raise


async def get_retention_run(
    session: AsyncSession,
    *,
    tenant_id: str,
    run_id: int,
) -> GovernanceRetentionRun | None:
    # Keep tenant scoping explicit for retention report reads.
    run = await session.get(GovernanceRetentionRun, run_id)
    if run is None or run.tenant_id != tenant_id:
        return None
    return run


async def create_legal_hold(
    *,
    session: AsyncSession,
    tenant_id: str,
    scope_type: str,
    scope_id: str | None,
    reason: str,
    expires_at: datetime | None,
    created_by_actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> LegalHold:
    # Persist hold creation and emit audit evidence for legal workflows.
    hold = LegalHold(
        tenant_id=tenant_id,
        scope_type=scope_type,
        scope_id=scope_id,
        reason=reason,
        expires_at=expires_at,
        created_by_actor_id=created_by_actor_id,
        is_active=True,
    )
    session.add(hold)
    await session.commit()
    await session.refresh(hold)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=created_by_actor_id,
        actor_role=actor_role,
        event_type="governance.legal_hold.created",
        outcome="success",
        resource_type="legal_hold",
        resource_id=str(hold.id),
        request_id=request_id,
        metadata={"scope_type": scope_type, "scope_id": scope_id, "reason": reason},
        commit=True,
        best_effort=True,
    )
    return hold


async def release_legal_hold(
    *,
    session: AsyncSession,
    hold: LegalHold,
    actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> LegalHold:
    # Keep release operation idempotent to simplify admin retries.
    hold.is_active = False
    hold.updated_at = _utc_now()
    await session.commit()
    await session.refresh(hold)
    await record_event(
        session=session,
        tenant_id=hold.tenant_id,
        actor_type="api_key",
        actor_id=actor_id,
        actor_role=actor_role,
        event_type="governance.legal_hold.released",
        outcome="success",
        resource_type="legal_hold",
        resource_id=str(hold.id),
        request_id=request_id,
        metadata={"scope_type": hold.scope_type, "scope_id": hold.scope_id},
        commit=True,
        best_effort=True,
    )
    return hold


async def _build_dsar_export_payload(session: AsyncSession, request: DsarRequest) -> dict[str, Any]:
    # Export scoped records while excluding secrets by design.
    tenant_id = request.tenant_id
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "request_type": request.request_type,
        "subject_type": request.subject_type,
        "subject_id": request.subject_id,
        "generated_at": _utc_now().isoformat(),
        "records": {},
    }
    if request.subject_type == "api_key":
        key = await session.get(ApiKey, request.subject_id)
        payload["records"]["api_key"] = None
        if key is not None and key.tenant_id == tenant_id:
            payload["records"]["api_key"] = {
                "id": key.id,
                "tenant_id": key.tenant_id,
                "user_id": key.user_id,
                "key_prefix": key.key_prefix,
                "name": key.name,
                "created_at": key.created_at.isoformat() if key.created_at else None,
                "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
                "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
            }
        return payload
    if request.subject_type == "session":
        session_row = await session.get(Session, request.subject_id)
        if session_row is None or session_row.tenant_id != tenant_id:
            payload["records"]["session"] = None
            return payload
        messages = (
            await session.execute(select(Message).where(Message.session_id == session_row.id))
        ).scalars().all()
        checkpoints = (
            await session.execute(select(Checkpoint).where(Checkpoint.session_id == session_row.id))
        ).scalars().all()
        payload["records"]["session"] = {
            "id": session_row.id,
            "tenant_id": session_row.tenant_id,
            "created_at": session_row.created_at.isoformat() if session_row.created_at else None,
            "last_seen_at": session_row.last_seen_at.isoformat() if session_row.last_seen_at else None,
        }
        payload["records"]["messages"] = [
            {"id": str(message.id), "role": message.role, "content": message.content}
            for message in messages
        ]
        payload["records"]["checkpoints"] = [
            {"id": str(checkpoint.id), "state_json": checkpoint.state_json}
            for checkpoint in checkpoints
        ]
        return payload
    if request.subject_type == "document":
        document = await session.get(Document, request.subject_id)
        payload["records"]["document"] = None
        if document is not None and document.tenant_id == tenant_id:
            payload["records"]["document"] = {
                "id": document.id,
                "tenant_id": document.tenant_id,
                "corpus_id": document.corpus_id,
                "filename": document.filename,
                "status": document.status,
                "created_at": document.created_at.isoformat() if document.created_at else None,
            }
            chunks = (
                await session.execute(select(Chunk).where(Chunk.document_id == document.id))
            ).scalars().all()
            payload["records"]["chunks"] = [
                {"id": str(chunk.id), "chunk_index": chunk.chunk_index, "text": chunk.text}
                for chunk in chunks
            ]
        return payload
    # Tenant export returns a compact report to avoid unbounded payload sizes.
    user_count = await session.scalar(select(func.count()).where(User.tenant_id == tenant_id))
    document_count = await session.scalar(select(func.count()).where(Document.tenant_id == tenant_id))
    session_count = await session.scalar(select(func.count()).where(Session.tenant_id == tenant_id))
    payload["records"]["tenant_summary"] = {
        "users": int(user_count or 0),
        "documents": int(document_count or 0),
        "sessions": int(session_count or 0),
    }
    return payload


async def _apply_dsar_destructive_action(
    session: AsyncSession,
    *,
    request: DsarRequest,
    mode: str,
) -> dict[str, int]:
    # Apply delete/anonymize operations for DSAR requests by subject scope.
    counts = {"deleted": 0, "anonymized": 0}
    tenant_id = request.tenant_id

    if request.subject_type == "api_key":
        key = await session.get(ApiKey, request.subject_id)
        if key is None or key.tenant_id != tenant_id:
            return counts
        if mode == "delete":
            await session.execute(delete(ApiKey).where(ApiKey.id == key.id))
            counts["deleted"] += 1
        else:
            key.name = "[ANONYMIZED]"
            counts["anonymized"] += 1
        return counts

    if request.subject_type == "session":
        session_row = await session.get(Session, request.subject_id)
        if session_row is None or session_row.tenant_id != tenant_id:
            return counts
        if mode == "delete":
            deleted_messages = await session.execute(delete(Message).where(Message.session_id == session_row.id))
            deleted_checkpoints = await session.execute(
                delete(Checkpoint).where(Checkpoint.session_id == session_row.id)
            )
            await session.execute(delete(Session).where(Session.id == session_row.id))
            counts["deleted"] += (deleted_messages.rowcount or 0) + (deleted_checkpoints.rowcount or 0) + 1
        else:
            updated_messages = await session.execute(
                update(Message).where(Message.session_id == session_row.id).values(content="[ANONYMIZED]")
            )
            updated_checkpoints = await session.execute(
                update(Checkpoint)
                .where(Checkpoint.session_id == session_row.id)
                .values(state_json={"anonymized": True})
            )
            counts["anonymized"] += (updated_messages.rowcount or 0) + (updated_checkpoints.rowcount or 0)
        return counts

    if request.subject_type == "document":
        document = await session.get(Document, request.subject_id)
        if document is None or document.tenant_id != tenant_id:
            return counts
        if mode == "delete":
            deleted_chunks = await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
            await session.execute(delete(Document).where(Document.id == document.id))
            counts["deleted"] += (deleted_chunks.rowcount or 0) + 1
        else:
            await session.execute(update(Chunk).where(Chunk.document_id == document.id).values(text="[ANONYMIZED]"))
            await session.execute(
                update(Document)
                .where(Document.id == document.id)
                .values(filename="[ANONYMIZED]", storage_path=None, metadata_json={"anonymized": True})
            )
            counts["anonymized"] += 1
        return counts

    # Tenant-scoped destructive requests apply to core tenant-bound records.
    if mode == "delete":
        document_ids = (
            await session.execute(select(Document.id).where(Document.tenant_id == tenant_id))
        ).scalars().all()
        if document_ids:
            deleted_chunks = await session.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))
            counts["deleted"] += deleted_chunks.rowcount or 0
        deleted_messages = await session.execute(
            delete(Message).where(Message.session_id.in_(select(Session.id).where(Session.tenant_id == tenant_id)))
        )
        deleted_checkpoints = await session.execute(
            delete(Checkpoint).where(
                Checkpoint.session_id.in_(select(Session.id).where(Session.tenant_id == tenant_id))
            )
        )
        deleted_sessions = await session.execute(delete(Session).where(Session.tenant_id == tenant_id))
        deleted_documents = await session.execute(delete(Document).where(Document.tenant_id == tenant_id))
        deleted_corpora = await session.execute(delete(Corpus).where(Corpus.tenant_id == tenant_id))
        deleted_keys = await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        counts["deleted"] += (
            (deleted_messages.rowcount or 0)
            + (deleted_checkpoints.rowcount or 0)
            + (deleted_sessions.rowcount or 0)
            + (deleted_documents.rowcount or 0)
            + (deleted_corpora.rowcount or 0)
            + (deleted_keys.rowcount or 0)
        )
    else:
        updated_messages = await session.execute(
            update(Message)
            .where(Message.session_id.in_(select(Session.id).where(Session.tenant_id == tenant_id)))
            .values(content="[ANONYMIZED]")
        )
        updated_checkpoints = await session.execute(
            update(Checkpoint)
            .where(Checkpoint.session_id.in_(select(Session.id).where(Session.tenant_id == tenant_id)))
            .values(state_json={"anonymized": True})
        )
        updated_documents = await session.execute(
            update(Document)
            .where(Document.tenant_id == tenant_id)
            .values(filename="[ANONYMIZED]", storage_path=None, metadata_json={"anonymized": True})
        )
        updated_keys = await session.execute(
            update(ApiKey).where(ApiKey.tenant_id == tenant_id).values(name="[ANONYMIZED]")
        )
        counts["anonymized"] += (
            (updated_messages.rowcount or 0)
            + (updated_checkpoints.rowcount or 0)
            + (updated_documents.rowcount or 0)
            + (updated_keys.rowcount or 0)
        )
    return counts


async def submit_dsar_request(
    *,
    session: AsyncSession,
    tenant_id: str,
    request_type: str,
    subject_type: str,
    subject_id: str,
    reason: str | None,
    requested_by_actor_id: str | None,
    actor_role: str | None,
    request_id: str | None,
) -> DsarRequest:
    # Create and execute DSAR workflow synchronously for deterministic API behavior.
    dsar = DsarRequest(
        tenant_id=tenant_id,
        request_type=request_type,
        subject_type=subject_type,
        subject_id=subject_id,
        status=DSAR_STATUS_PENDING,
        requested_by_actor_id=requested_by_actor_id,
        report_json={"reason": reason},
    )
    session.add(dsar)
    await session.commit()
    await session.refresh(dsar)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=requested_by_actor_id,
        actor_role=actor_role,
        event_type="governance.dsar.requested",
        outcome="success",
        resource_type="dsar_request",
        resource_id=str(dsar.id),
        request_id=request_id,
        metadata={
            "request_type": request_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
        },
        commit=True,
        best_effort=True,
    )

    dsar.status = DSAR_STATUS_RUNNING
    await session.commit()
    await session.refresh(dsar)
    await record_event(
        session=session,
        tenant_id=tenant_id,
        actor_type="api_key",
        actor_id=requested_by_actor_id,
        actor_role=actor_role,
        event_type="governance.dsar.running",
        outcome="success",
        resource_type="dsar_request",
        resource_id=str(dsar.id),
        request_id=request_id,
        metadata={"request_type": request_type, "subject_type": subject_type},
        commit=True,
        best_effort=True,
    )

    try:
        decision = await enforce_policy(
            session=session,
            tenant_id=tenant_id,
            actor_id=requested_by_actor_id,
            actor_role=actor_role,
            rule_key="dsar.execute",
            context={
                "endpoint": "/admin/governance/dsar",
                "method": "POST",
                "request_type": request_type,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "actor_role": actor_role,
            },
            request_id=request_id,
            allow_require_approval=True,
        )
        if decision.require_approval and request_type in {"delete", "anonymize"}:
            dsar.status = DSAR_STATUS_REJECTED
            dsar.error_code = "DSAR_REQUIRES_APPROVAL"
            dsar.error_message = decision.message or "Approval required by governance policy"
            dsar.completed_at = _utc_now()
            await session.commit()
            await session.refresh(dsar)
            await record_event(
                session=session,
                tenant_id=tenant_id,
                actor_type="api_key",
                actor_id=requested_by_actor_id,
                actor_role=actor_role,
                event_type="governance.dsar.rejected",
                outcome="failure",
                resource_type="dsar_request",
                resource_id=str(dsar.id),
                request_id=request_id,
                metadata={"reason": dsar.error_message},
                error_code=dsar.error_code,
                commit=True,
                best_effort=True,
            )
            return dsar

        if request_type in {"delete", "anonymize"}:
            hold_scope = {
                "api_key": LEGAL_HOLD_SCOPE_USER_KEY,
                "session": LEGAL_HOLD_SCOPE_SESSION,
                "document": LEGAL_HOLD_SCOPE_DOCUMENT,
                "tenant": LEGAL_HOLD_SCOPE_TENANT,
            }[subject_type]
            hold = await find_applicable_legal_hold(
                session,
                tenant_id=tenant_id,
                scope_type=hold_scope,
                scope_id=subject_id if hold_scope != LEGAL_HOLD_SCOPE_TENANT else None,
            )
            if hold is not None:
                dsar.status = DSAR_STATUS_REJECTED
                dsar.error_code = "LEGAL_HOLD_ACTIVE"
                dsar.error_message = "DSAR blocked by active legal hold"
                dsar.completed_at = _utc_now()
                await session.commit()
                await session.refresh(dsar)
                await record_event(
                    session=session,
                    tenant_id=tenant_id,
                    actor_type="api_key",
                    actor_id=requested_by_actor_id,
                    actor_role=actor_role,
                    event_type="governance.dsar.rejected",
                    outcome="failure",
                    resource_type="dsar_request",
                    resource_id=str(dsar.id),
                    request_id=request_id,
                    metadata={"reason": dsar.error_message},
                    error_code="LEGAL_HOLD_ACTIVE",
                    commit=True,
                    best_effort=True,
                )
                return dsar

        if request_type == "export":
            export_payload = await _build_dsar_export_payload(session, dsar)
            # Encrypt DSAR export artifacts at rest when crypto is available.
            payload_bytes = gzip.compress(json.dumps(export_payload, ensure_ascii=False).encode("utf-8"))
            blob = await store_encrypted_blob(
                session,
                tenant_id=tenant_id,
                resource_type=CRYPTO_RESOURCE_DSAR,
                resource_id=str(dsar.id),
                plaintext=payload_bytes,
                created_at=_utc_now(),
            )
            artifact_sha = hashlib.sha256(payload_bytes).hexdigest()
            manifest: dict[str, Any] = {
                "dsar_id": dsar.id,
                "tenant_id": tenant_id,
                "request_type": request_type,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "artifact_sha256": artifact_sha,
                "artifact_size_bytes": len(payload_bytes),
                "generated_at": _utc_now().isoformat(),
            }
            if blob is not None:
                manifest["encrypted_blob_id"] = blob.id
            signature = _sign_payload(json.dumps(manifest, sort_keys=True).encode("utf-8"))
            if signature:
                manifest["signature"] = signature
            target_dir = _ensure_artifact_dir() / f"tenant_{tenant_id}" / f"dsar_{dsar.id}"
            target_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = target_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            if blob is not None:
                dsar.artifact_uri = f"encrypted_blob:{blob.id}"
            else:
                # Fall back to legacy plaintext artifact storage when crypto is unavailable.
                artifact_path = target_dir / "export.json.gz"
                artifact_path.write_bytes(payload_bytes)
                dsar.artifact_uri = str(artifact_path)
            dsar.report_json = {"manifest_path": str(manifest_path), "artifact_sha256": artifact_sha}
        else:
            policy = await get_or_create_retention_policy(session, tenant_id)
            mode = "anonymize" if (request_type == "anonymize" or policy.anonymize_instead_of_delete) else "delete"
            counts = await _apply_dsar_destructive_action(
                session,
                request=dsar,
                mode=mode,
            )
            dsar.report_json = {"mode": mode, "counts": counts}
        dsar.status = DSAR_STATUS_COMPLETED
        dsar.completed_at = _utc_now()
        await session.commit()
        await session.refresh(dsar)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=requested_by_actor_id,
            actor_role=actor_role,
            event_type="governance.dsar.completed",
            outcome="success",
            resource_type="dsar_request",
            resource_id=str(dsar.id),
            request_id=request_id,
            metadata={"request_type": request_type, "subject_type": subject_type},
            commit=True,
            best_effort=True,
        )
        return dsar
    except HTTPException as exc:
        dsar.status = DSAR_STATUS_REJECTED
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        dsar.error_code = str(detail.get("code") or "POLICY_DENIED")
        dsar.error_message = str(detail.get("message") or "DSAR request rejected")
        dsar.completed_at = _utc_now()
        await session.commit()
        await session.refresh(dsar)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=requested_by_actor_id,
            actor_role=actor_role,
            event_type="governance.dsar.rejected",
            outcome="failure",
            resource_type="dsar_request",
            resource_id=str(dsar.id),
            request_id=request_id,
            metadata={"reason": dsar.error_message},
            error_code=dsar.error_code,
            commit=True,
            best_effort=True,
        )
        if dsar.error_code in {"ENCRYPTION_REQUIRED", "KMS_UNAVAILABLE"}:
            raise
        return dsar
    except Exception as exc:  # noqa: BLE001 - keep DSAR failures visible and auditable.
        dsar.status = DSAR_STATUS_FAILED
        dsar.error_code = "DSAR_FAILED"
        dsar.error_message = str(exc)
        dsar.completed_at = _utc_now()
        await session.commit()
        await session.refresh(dsar)
        await record_event(
            session=session,
            tenant_id=tenant_id,
            actor_type="api_key",
            actor_id=requested_by_actor_id,
            actor_role=actor_role,
            event_type="governance.dsar.failed",
            outcome="failure",
            resource_type="dsar_request",
            resource_id=str(dsar.id),
            request_id=request_id,
            metadata={"request_type": request_type, "subject_type": subject_type},
            error_code="DSAR_FAILED",
            commit=True,
            best_effort=True,
        )
        return dsar


async def governance_status_snapshot(session: AsyncSession, tenant_id: str) -> dict[str, Any]:
    # Provide a compact compliance posture summary for ops dashboards.
    settings = get_settings()
    active_holds = await session.scalar(
        select(func.count()).where(
            LegalHold.tenant_id == tenant_id,
            LegalHold.is_active.is_(True),
            or_(LegalHold.expires_at.is_(None), LegalHold.expires_at > _utc_now()),
        )
    )
    pending_dsar = await session.scalar(
        select(func.count()).where(
            DsarRequest.tenant_id == tenant_id,
            DsarRequest.status.in_([DSAR_STATUS_PENDING, DSAR_STATUS_RUNNING]),
        )
    )
    last_retention = (
        await session.execute(
            select(GovernanceRetentionRun)
            .where(GovernanceRetentionRun.tenant_id == tenant_id)
            .order_by(GovernanceRetentionRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    active_key = (
        await session.execute(
            select(TenantKey)
            .where(TenantKey.tenant_id == tenant_id, TenantKey.status == "active")
            .order_by(TenantKey.key_version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    last_rotation = (
        await session.execute(
            select(KeyRotationJob)
            .where(KeyRotationJob.tenant_id == tenant_id)
            .order_by(KeyRotationJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    encrypted_count = await session.scalar(
        select(func.count()).where(EncryptedBlob.tenant_id == tenant_id)
    )
    now = _utc_now()
    key_age_days = None
    overdue_rotations = 0
    if active_key and active_key.activated_at:
        key_age_days = (now - active_key.activated_at).days
        if key_age_days > settings.crypto_rotation_interval_days:
            overdue_rotations = 1
    posture = "healthy"
    if last_retention is None or last_retention.status == "failed":
        posture = "at_risk"
    if (pending_dsar or 0) > 50:
        posture = "blocked"
    return {
        "policy_engine_enabled": settings.governance_policy_engine_enabled,
        "active_holds_count": int(active_holds or 0),
        "pending_dsar_count": int(pending_dsar or 0),
        "last_retention_run": {
            "id": last_retention.id if last_retention else None,
            "status": last_retention.status if last_retention else "unknown",
            "started_at": last_retention.started_at.isoformat() if last_retention else None,
            "completed_at": last_retention.completed_at.isoformat() if last_retention and last_retention.completed_at else None,
        },
        "crypto": {
            "crypto_enabled": settings.crypto_enabled,
            "active_key_age_days": key_age_days,
            "overdue_rotations": overdue_rotations,
            "unencrypted_sensitive_items": 0,
            "encrypted_sensitive_items": int(encrypted_count or 0),
            "last_rotation_status": last_rotation.status if last_rotation else "unknown",
        },
        "compliance_posture": posture,
    }


async def governance_evidence(
    session: AsyncSession,
    *,
    tenant_id: str,
    window_days: int,
) -> GovernanceEvidenceBundle:
    # Aggregate retention, DSAR, hold, and policy evidence metadata for audits.
    settings = get_settings()
    bounded_window = max(1, min(window_days, settings.governance_evidence_max_window_days))
    cutoff = _utc_now() - timedelta(days=bounded_window)

    retention_rows = (
        await session.execute(
            select(GovernanceRetentionRun)
            .where(
                GovernanceRetentionRun.tenant_id == tenant_id,
                GovernanceRetentionRun.started_at >= cutoff,
            )
            .order_by(GovernanceRetentionRun.started_at.desc())
        )
    ).scalars().all()
    dsar_rows = (
        await session.execute(
            select(DsarRequest)
            .where(
                DsarRequest.tenant_id == tenant_id,
                DsarRequest.created_at >= cutoff,
            )
            .order_by(DsarRequest.created_at.desc())
        )
    ).scalars().all()
    hold_rows = (
        await session.execute(
            select(LegalHold)
            .where(
                LegalHold.tenant_id == tenant_id,
                LegalHold.updated_at >= cutoff,
            )
            .order_by(LegalHold.updated_at.desc())
        )
    ).scalars().all()
    policy_rows = (
        await session.execute(
            select(PolicyRule)
            .where(
                or_(PolicyRule.tenant_id == tenant_id, PolicyRule.tenant_id.is_(None)),
                PolicyRule.updated_at >= cutoff,
            )
            .order_by(PolicyRule.updated_at.desc())
        )
    ).scalars().all()

    return GovernanceEvidenceBundle(
        retention_runs=[
            {
                "id": row.id,
                "status": row.status,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            }
            for row in retention_rows
        ],
        dsar_requests=[
            {
                "id": row.id,
                "status": row.status,
                "request_type": row.request_type,
                "subject_type": row.subject_type,
                "subject_id": row.subject_id,
                "artifact_uri": row.artifact_uri,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            }
            for row in dsar_rows
        ],
        legal_holds=[
            {
                "id": row.id,
                "scope_type": row.scope_type,
                "scope_id": row.scope_id,
                "is_active": row.is_active,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in hold_rows
        ],
        policy_changes=[
            {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "rule_key": row.rule_key,
                "enabled": row.enabled,
                "priority": row.priority,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in policy_rows
        ],
    )
