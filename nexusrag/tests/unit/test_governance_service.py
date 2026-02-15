from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from nexusrag.domain.models import (
    Checkpoint,
    Chunk,
    Document,
    DsarRequest,
    LegalHold,
    Message,
    PolicyRule,
    RetentionPolicy,
    Session,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.governance import (
    DSAR_STATUS_COMPLETED,
    DSAR_STATUS_REJECTED,
    LEGAL_HOLD_SCOPE_DOCUMENT,
    LEGAL_HOLD_SCOPE_SESSION,
    _retention_mode,
    find_applicable_legal_hold,
    run_retention_for_tenant,
    submit_dsar_request,
)
from nexusrag.services.policy_engine import evaluate_policy


async def _reset_governance_rows() -> None:
    # Keep unit tests deterministic by clearing governance rows before each assertion.
    async with SessionLocal() as session:
        await session.execute(delete(DsarRequest))
        await session.execute(delete(LegalHold))
        await session.execute(delete(PolicyRule))
        await session.execute(delete(Message))
        # Delete checkpoint children before sessions to satisfy FK constraints.
        await session.execute(delete(Checkpoint))
        await session.execute(delete(Chunk))
        await session.execute(delete(Document))
        await session.execute(delete(Session))
        await session.execute(delete(RetentionPolicy))
        await session.commit()


@pytest.mark.asyncio
async def test_policy_engine_precedence_and_deterministic_resolution() -> None:
    await _reset_governance_rows()
    tenant_id = f"t-pol-{uuid4().hex}"
    async with SessionLocal() as session:
        session.add(
            PolicyRule(
                tenant_id=tenant_id,
                rule_key="documents.delete",
                enabled=True,
                priority=10,
                condition_json={"method": "DELETE"},
                action_json={"type": "allow"},
            )
        )
        session.add(
            PolicyRule(
                tenant_id=tenant_id,
                rule_key="documents.delete",
                enabled=True,
                priority=100,
                condition_json={"method": "DELETE"},
                action_json={"type": "deny", "code": "POLICY_DENIED"},
            )
        )
        await session.commit()

        context = {"method": "DELETE", "endpoint": "/v1/documents/doc1"}
        first = await evaluate_policy(
            session=session,
            tenant_id=tenant_id,
            rule_key="documents.delete",
            context=context,
        )
        second = await evaluate_policy(
            session=session,
            tenant_id=tenant_id,
            rule_key="documents.delete",
            context=context,
        )
    assert first.allowed is False
    assert first.code == "POLICY_DENIED"
    assert first.rule_id == second.rule_id


@pytest.mark.asyncio
async def test_legal_hold_matcher_scope_resolution() -> None:
    await _reset_governance_rows()
    tenant_id = f"t-hold-{uuid4().hex}"
    document_id = f"doc-{uuid4().hex}"
    async with SessionLocal() as session:
        session.add(
            LegalHold(
                tenant_id=tenant_id,
                scope_type=LEGAL_HOLD_SCOPE_DOCUMENT,
                scope_id=document_id,
                reason="litigation",
                created_by_actor_id="ak1",
                is_active=True,
            )
        )
        await session.commit()
        hold = await find_applicable_legal_hold(
            session,
            tenant_id=tenant_id,
            scope_type=LEGAL_HOLD_SCOPE_DOCUMENT,
            scope_id=document_id,
        )
        missing = await find_applicable_legal_hold(
            session,
            tenant_id=tenant_id,
            scope_type=LEGAL_HOLD_SCOPE_DOCUMENT,
            scope_id="other",
        )
    assert hold is not None
    assert hold.scope_id == document_id
    assert missing is None


def test_retention_mode_selection_defaults_to_anonymize() -> None:
    policy = RetentionPolicy(
        tenant_id="t1",
        hard_delete_enabled=False,
        anonymize_instead_of_delete=True,
    )
    assert _retention_mode(policy) == "anonymize"
    policy.hard_delete_enabled = True
    policy.anonymize_instead_of_delete = False
    assert _retention_mode(policy) == "hard_delete"


@pytest.mark.asyncio
async def test_retention_honors_hold_exclusions() -> None:
    await _reset_governance_rows()
    tenant_id = f"t-ret-{uuid4().hex}"
    session_id = f"s-ret-{uuid4().hex}"
    old_ts = datetime.now(timezone.utc) - timedelta(days=10)
    async with SessionLocal() as session:
        session.add(Session(id=session_id, tenant_id=tenant_id))
        # Persist parent session first; Message has an FK and tests should not rely on mapper flush ordering.
        await session.flush()
        session.add(Message(session_id=session_id, role="user", content="hello", created_at=old_ts))
        session.add(
            RetentionPolicy(
                tenant_id=tenant_id,
                messages_ttl_days=1,
                hard_delete_enabled=True,
                anonymize_instead_of_delete=False,
            )
        )
        session.add(
            LegalHold(
                tenant_id=tenant_id,
                scope_type=LEGAL_HOLD_SCOPE_SESSION,
                scope_id=session_id,
                reason="hold",
                created_by_actor_id="ak1",
                is_active=True,
            )
        )
        await session.commit()

        run = await run_retention_for_tenant(
            session=session,
            tenant_id=tenant_id,
            actor_id="ak1",
            actor_role="admin",
            request_id="req-retention",
        )
        remaining = await session.scalar(
            select(func.count()).where(Message.session_id == session_id)
        )
    assert run.status == "completed"
    assert run.report_json is not None
    assert run.report_json["categories"]["messages"]["skipped_hold"] == 1
    assert int(remaining or 0) == 1


@pytest.mark.asyncio
async def test_dsar_state_transitions_and_hold_blocking() -> None:
    await _reset_governance_rows()
    tenant_id = f"t-dsar-{uuid4().hex}"
    document_id = f"d-dsar-{uuid4().hex}"
    async with SessionLocal() as session:
        session.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                corpus_id="c1",
                filename="doc.txt",
                content_type="text/plain",
                source="raw_text",
                ingest_source="raw_text",
                storage_path=None,
                metadata_json={},
                status="succeeded",
            )
        )
        session.add(
            LegalHold(
                tenant_id=tenant_id,
                scope_type=LEGAL_HOLD_SCOPE_DOCUMENT,
                scope_id=document_id,
                reason="active hold",
                created_by_actor_id="ak1",
                is_active=True,
            )
        )
        await session.commit()

        rejected = await submit_dsar_request(
            session=session,
            tenant_id=tenant_id,
            request_type="delete",
            subject_type="document",
            subject_id=document_id,
            reason="erase",
            requested_by_actor_id="ak1",
            actor_role="admin",
            request_id="req-dsar-delete",
        )
        exported = await submit_dsar_request(
            session=session,
            tenant_id=tenant_id,
            request_type="export",
            subject_type="document",
            subject_id=document_id,
            reason="export",
            requested_by_actor_id="ak1",
            actor_role="admin",
            request_id="req-dsar-export",
        )
    assert rejected.status == DSAR_STATUS_REJECTED
    assert rejected.error_code == "LEGAL_HOLD_ACTIVE"
    assert exported.status == DSAR_STATUS_COMPLETED
    assert exported.artifact_uri is not None
    assert exported.artifact_uri.startswith("encrypted_blob:")
