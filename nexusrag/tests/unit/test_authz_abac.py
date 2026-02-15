from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from nexusrag.apps.api.deps import Principal
from nexusrag.domain.models import AuthorizationPolicy, Document, DocumentPermission
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.authz.abac import evaluate_document_permissions, evaluate_policy_set
from nexusrag.services.authz.evaluator import (
    PolicyInvalidError,
    PolicyTooComplexError,
    evaluate_condition,
    validate_condition,
)


def _policy(
    *,
    effect: str,
    resource_type: str = "document",
    action: str = "read",
    priority: int = 10,
    condition_json: dict | None = None,
) -> AuthorizationPolicy:
    # Build in-memory policy objects for evaluator tests.
    return AuthorizationPolicy(
        id=uuid4().hex,
        tenant_id="t-policy",
        name=f"policy-{uuid4().hex}",
        version=1,
        effect=effect,
        resource_type=resource_type,
        action=action,
        condition_json=condition_json or {},
        priority=priority,
        enabled=True,
        created_by="test",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_evaluator_truth_table() -> None:
    context = {
        "principal": {"role": "admin", "groups": ["eng", "ops"]},
        "resource": {"owner": "u-1", "labels": {"sensitivity": "high"}},
        "request": {"time": "2026-02-15T10:00:00Z"},
    }
    cases = [
        ({"eq": [{"var": "principal.role"}, "admin"]}, True),
        ({"ne": [{"var": "principal.role"}, "reader"]}, True),
        ({"in": [{"var": "principal.role"}, ["admin", "editor"]]}, True),
        ({"not_in": [{"var": "principal.role"}, ["reader"]]}, True),
        ({"gt": [5, 2]}, True),
        ({"gte": [2, 2]}, True),
        ({"lt": [1, 2]}, True),
        ({"lte": [2, 2]}, True),
        ({"contains": [{"var": "principal.groups"}, "eng"]}, True),
        ({"starts_with": ["high-confidential", "high"]}, True),
        (
            {"time_between": [{"var": "request.time"}, {"start": "09:00", "end": "18:00"}]},
            True,
        ),
        (
            {"date_between": ["2026-02-15", {"start": "2026-02-01", "end": "2026-02-28"}]},
            True,
        ),
        (
            {
                "all": [
                    {"eq": [{"var": "principal.role"}, "admin"]},
                    {"contains": [{"var": "principal.groups"}, "ops"]},
                ]
            },
            True,
        ),
        (
            {
                "any": [
                    {"eq": [{"var": "principal.role"}, "reader"]},
                    {"eq": [{"var": "principal.role"}, "admin"]},
                ]
            },
            True,
        ),
        ({"not": {"eq": [{"var": "principal.role"}, "reader"]}}, True),
    ]
    for condition, expected in cases:
        assert evaluate_condition(condition, context) is expected


def test_validate_condition_rejects_invalid_operator() -> None:
    with pytest.raises(PolicyInvalidError):
        validate_condition({"unsupported": [1]}, max_depth=3)


def test_validate_condition_rejects_depth() -> None:
    condition = {"all": [{"all": [{"all": [{"eq": [1, 1]}]}]}]}
    with pytest.raises(PolicyTooComplexError):
        validate_condition(condition, max_depth=2)


def test_deny_overrides_allow() -> None:
    policies = [
        _policy(effect="allow", priority=200, condition_json={"eq": [1, 1]}),
        _policy(effect="deny", priority=10, condition_json={"eq": [1, 1]}),
    ]
    policies.sort(key=lambda item: (-item.priority, item.id))
    decision = evaluate_policy_set(
        policies=policies,
        resource_type="document",
        action="read",
        context={"principal": {}, "resource": {}, "request": {}},
        include_trace=True,
        default_deny=True,
    )
    assert decision.allowed is False
    assert decision.reason == "policy_deny"


def test_invalid_policy_fails_closed() -> None:
    policies = [_policy(effect="allow", condition_json={"bad": "payload"})]
    decision = evaluate_policy_set(
        policies=policies,
        resource_type="document",
        action="read",
        context={"principal": {}, "resource": {}, "request": {}},
        include_trace=True,
        default_deny=True,
    )
    assert decision.allowed is False
    assert decision.reason == "policy_invalid"
    assert decision.matched_policy_id == policies[0].id


def test_policy_trace_reports_matches() -> None:
    policy = _policy(effect="allow", condition_json={"eq": [1, 1]})
    decision = evaluate_policy_set(
        policies=[policy],
        resource_type="document",
        action="read",
        context={"principal": {}, "resource": {}, "request": {}},
        include_trace=True,
        default_deny=True,
    )
    assert decision.allowed is True
    assert decision.matched_policy_id == policy.id
    assert decision.trace
    assert decision.trace[0]["matched"] is True


@pytest.mark.asyncio
async def test_document_permission_expiration() -> None:
    tenant_id = "t-acl"
    doc_id = f"doc-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    principal = Principal(
        subject_id="user-1",
        tenant_id=tenant_id,
        role="reader",
        api_key_id="key-1",
        auth_method="api_key",
        subject_type="user",
    )

    async with SessionLocal() as session:
        session.add(
            Document(
                id=doc_id,
                tenant_id=tenant_id,
                corpus_id="c-1",
                filename="doc.txt",
                content_type="text/plain",
                source="raw_text",
                ingest_source="raw_text",
                status="succeeded",
            )
        )
        session.add(
            DocumentPermission(
                id=uuid4().hex,
                tenant_id=tenant_id,
                document_id=doc_id,
                principal_type="user",
                principal_id=principal.subject_id,
                permission="read",
                granted_by=principal.api_key_id,
                expires_at=now - timedelta(minutes=1),
            )
        )
        await session.commit()

        allowed = await evaluate_document_permissions(
            session=session,
            principal=principal,
            document_id=doc_id,
            action="read",
            now=now,
        )
        assert allowed is False

        session.add(
            DocumentPermission(
                id=uuid4().hex,
                tenant_id=tenant_id,
                document_id=doc_id,
                principal_type="user",
                principal_id=principal.subject_id,
                permission="write",
                granted_by=principal.api_key_id,
                expires_at=now + timedelta(days=1),
            )
        )
        await session.commit()

        allowed = await evaluate_document_permissions(
            session=session,
            principal=principal,
            document_id=doc_id,
            action="read",
            now=now,
        )
        assert allowed is True
