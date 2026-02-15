from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.apps.api.deps import Principal
from nexusrag.apps.api.rate_limit import route_class_for_request
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    AuthorizationPolicy,
    Document,
    DocumentLabel,
    DocumentPermission,
    ScimGroup,
    ScimGroupMembership,
    TenantPlanAssignment,
)
from nexusrag.persistence.guards import tenant_predicate
from nexusrag.persistence.repos import authz as authz_repo
from nexusrag.services.audit import get_request_context, record_event
from nexusrag.services.auth.api_keys import normalize_role
from nexusrag.services.authz.evaluator import (
    PolicyInvalidError,
    PolicyTooComplexError,
    evaluate_condition,
    policy_size_bytes,
    validate_condition,
)


_ACTION_PERMISSIONS: dict[str, set[str]] = {
    # Allow broader permissions to satisfy read actions.
    "read": {"read", "write", "delete", "reindex", "owner"},
    "write": {"write", "delete", "owner"},
    "delete": {"delete", "owner"},
    "reindex": {"reindex", "owner"},
}


@dataclass(frozen=True)
class AbacDecision:
    # Return deterministic ABAC decisions for auditing and enforcement.
    allowed: bool
    reason: str
    matched_policy_id: str | None
    trace: list[dict[str, Any]]


def _authz_denied(message: str) -> HTTPException:
    # Standardize ABAC denial responses for clients.
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "AUTHZ_DENIED", "message": message},
    )


def _authz_policy_invalid(message: str) -> HTTPException:
    # Report invalid policies using stable error envelopes.
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "AUTHZ_POLICY_INVALID", "message": message},
    )


def _authz_policy_complex(message: str) -> HTTPException:
    # Report policy complexity violations consistently.
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "AUTHZ_POLICY_TOO_COMPLEX", "message": message},
    )


def _utc_now() -> datetime:
    # Keep ABAC evaluation timestamps in UTC.
    return datetime.now(timezone.utc)


def validate_policy_condition(condition_json: dict[str, Any] | None) -> None:
    # Apply size and depth checks to policy conditions before persistence.
    settings = get_settings()
    if condition_json is None:
        return
    if policy_size_bytes(condition_json) > settings.authz_max_policy_bytes:
        raise _authz_policy_complex("Policy condition exceeds size limits")
    try:
        validate_condition(condition_json, max_depth=settings.authz_max_policy_depth)
    except PolicyTooComplexError as exc:
        raise _authz_policy_complex(exc.message) from exc
    except PolicyInvalidError as exc:
        raise _authz_policy_invalid(exc.message) from exc


async def evaluate_policies(
    *,
    session: AsyncSession,
    tenant_id: str,
    resource_type: str,
    action: str,
    context: dict[str, Any],
    include_trace: bool = False,
) -> AbacDecision:
    # Evaluate ABAC policies with deny-first ordering and default deny behavior.
    settings = get_settings()
    if not settings.authz_abac_enabled:
        return AbacDecision(allowed=True, reason="abac_disabled", matched_policy_id=None, trace=[])

    stmt = (
        select(AuthorizationPolicy)
        .where(
            AuthorizationPolicy.enabled.is_(True),
            or_(AuthorizationPolicy.tenant_id == tenant_id, AuthorizationPolicy.tenant_id.is_(None)),
        )
        .order_by(AuthorizationPolicy.priority.desc(), AuthorizationPolicy.id.asc())
    )
    policies = list((await session.execute(stmt)).scalars().all())

    def _matches_scope(policy: AuthorizationPolicy) -> bool:
        return policy.resource_type in {resource_type, "*"} and policy.action in {action, "*"}

    return evaluate_policy_set(
        policies=policies,
        resource_type=resource_type,
        action=action,
        context=context,
        include_trace=include_trace,
        default_deny=settings.authz_default_deny,
    )


def evaluate_policy_set(
    *,
    policies: list[AuthorizationPolicy],
    resource_type: str,
    action: str,
    context: dict[str, Any],
    include_trace: bool,
    default_deny: bool,
) -> AbacDecision:
    # Evaluate an explicit policy set to support simulation and testing.
    active_policies = [policy for policy in policies if policy.enabled]

    def _matches_scope(policy: AuthorizationPolicy) -> bool:
        return policy.resource_type in {resource_type, "*"} and policy.action in {action, "*"}

    trace: list[dict[str, Any]] = []
    for effect in ("deny", "allow"):
        for policy in active_policies:
            if policy.effect != effect or not _matches_scope(policy):
                continue
            try:
                matched = evaluate_condition(policy.condition_json or {}, context)
            except (PolicyInvalidError, PolicyTooComplexError) as exc:
                trace.append(
                    {
                        "policy_id": policy.id,
                        "effect": policy.effect,
                        "matched": False,
                        "error": exc.message,
                    }
                )
                return AbacDecision(
                    allowed=False,
                    reason="policy_invalid",
                    matched_policy_id=policy.id,
                    trace=trace if include_trace else [],
                )
            trace.append(
                {
                    "policy_id": policy.id,
                    "effect": policy.effect,
                    "matched": matched,
                }
            )
            if matched:
                return AbacDecision(
                    allowed=effect == "allow",
                    reason=f"policy_{effect}",
                    matched_policy_id=policy.id,
                    trace=trace if include_trace else [],
                )

    if default_deny:
        return AbacDecision(
            allowed=False,
            reason="default_deny",
            matched_policy_id=None,
            trace=trace if include_trace else [],
        )
    return AbacDecision(
        allowed=True,
        reason="default_allow",
        matched_policy_id=None,
        trace=trace if include_trace else [],
    )


async def load_principal_attributes(
    *,
    session: AsyncSession,
    principal: Principal,
    commit: bool = False,
) -> dict[str, Any]:
    # Resolve principal attributes for ABAC evaluation and cache them.
    normalized_role = normalize_role(principal.role)
    plan_id = await _fetch_plan_id(session=session, tenant_id=principal.tenant_id)
    groups = await _fetch_groups(session=session, tenant_id=principal.tenant_id, user_id=principal.subject_id)
    attrs = {
        "role": normalized_role,
        "tenant_id": principal.tenant_id,
        "plan": plan_id,
        "groups": groups,
        "auth_method": principal.auth_method,
    }
    await authz_repo.upsert_principal_attributes(
        session,
        tenant_id=principal.tenant_id,
        principal_type=principal.subject_type,
        principal_id=principal.subject_id,
        attrs_json=attrs,
        now=_utc_now(),
    )
    if commit:
        await session.commit()
    return attrs


async def build_document_context(
    *,
    session: AsyncSession,
    principal: Principal,
    document: Document,
    request: Any | None,
    principal_attrs: dict[str, Any] | None = None,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    # Assemble ABAC context with principal, resource, and request attributes.
    if labels is None:
        labels_map = await _load_document_labels(
            session=session,
            tenant_id=document.tenant_id,
            document_ids=[document.id],
        )
        labels = labels_map.get(document.id, {})
    if principal_attrs is None:
        principal_attrs = await load_principal_attributes(session=session, principal=principal, commit=False)
    request_ctx = get_request_context(request) if request is not None else {}
    route_class = route_class_for_request(request) if request is not None else None
    request_path = request.url.path if request is not None else None
    return {
        "principal": {
            "id": principal.subject_id,
            "tenant_id": principal.tenant_id,
            "role": principal_attrs.get("role"),
            "plan": principal_attrs.get("plan"),
            "groups": principal_attrs.get("groups"),
            "auth_method": principal.auth_method,
        },
        "resource": {
            "id": document.id,
            "tenant_id": document.tenant_id,
            "corpus_id": document.corpus_id,
            "status": document.status,
            "content_type": document.content_type,
            "labels": labels,
            "metadata": document.metadata_json,
        },
        "request": {
            "ip": request_ctx.get("ip_address"),
            "route_class": route_class,
            "time": _utc_now().isoformat(),
            "path": request_path,
        },
    }


async def evaluate_document_permissions(
    *,
    session: AsyncSession,
    principal: Principal,
    document_id: str,
    action: str,
    now: datetime,
) -> bool:
    # Evaluate explicit document permissions for the principal.
    settings = get_settings()
    if settings.authz_admin_bypass_document_acl and principal.role == "admin":
        return True
    allowed_actions = _ACTION_PERMISSIONS.get(action, {action})
    predicates = [
        and_(
            DocumentPermission.principal_type == "user",
            DocumentPermission.principal_id == principal.subject_id,
        ),
        and_(
            DocumentPermission.principal_type == "role",
            DocumentPermission.principal_id == principal.role,
        ),
    ]
    if principal.auth_method == "api_key":
        predicates.append(
            and_(
                DocumentPermission.principal_type == "api_key",
                DocumentPermission.principal_id == principal.api_key_id,
            )
        )
    groups = await _fetch_groups(session=session, tenant_id=principal.tenant_id, user_id=principal.subject_id)
    if groups:
        predicates.append(
            and_(
                DocumentPermission.principal_type == "group",
                DocumentPermission.principal_id.in_(groups),
            )
        )
    stmt = select(DocumentPermission).where(
        tenant_predicate(DocumentPermission, principal.tenant_id),
        DocumentPermission.document_id == document_id,
        or_(*predicates),
        or_(DocumentPermission.expires_at.is_(None), DocumentPermission.expires_at > now),
    )
    rows = list((await session.execute(stmt)).scalars().all())
    for row in rows:
        if row.permission in allowed_actions:
            return True
    return False


async def load_document_permissions_for_principal(
    *,
    session: AsyncSession,
    principal: Principal,
    document_ids: list[str],
    now: datetime,
) -> dict[str, set[str]]:
    # Batch-load document permissions for list filtering and cursor-safe paging.
    if not document_ids:
        return {}
    predicates = [
        and_(
            DocumentPermission.principal_type == "user",
            DocumentPermission.principal_id == principal.subject_id,
        ),
        and_(
            DocumentPermission.principal_type == "role",
            DocumentPermission.principal_id == principal.role,
        ),
    ]
    if principal.auth_method == "api_key":
        predicates.append(
            and_(
                DocumentPermission.principal_type == "api_key",
                DocumentPermission.principal_id == principal.api_key_id,
            )
        )
    groups = await _fetch_groups(session=session, tenant_id=principal.tenant_id, user_id=principal.subject_id)
    if groups:
        predicates.append(
            and_(
                DocumentPermission.principal_type == "group",
                DocumentPermission.principal_id.in_(groups),
            )
        )
    stmt = select(DocumentPermission).where(
        tenant_predicate(DocumentPermission, principal.tenant_id),
        DocumentPermission.document_id.in_(document_ids),
        or_(*predicates),
        or_(DocumentPermission.expires_at.is_(None), DocumentPermission.expires_at > now),
    )
    rows = list((await session.execute(stmt)).scalars().all())
    permissions: dict[str, set[str]] = {}
    for row in rows:
        permissions.setdefault(row.document_id, set()).add(row.permission)
    return permissions


def document_acl_allows(*, permissions: set[str] | None, action: str) -> bool:
    # Map stored document permissions to actionable rights.
    if not permissions:
        return False
    allowed = _ACTION_PERMISSIONS.get(action, {action})
    return bool(set(permissions) & allowed)


async def filter_documents_for_principal(
    *,
    session: AsyncSession,
    principal: Principal,
    documents: list[Document],
    action: str,
    request: Any | None,
) -> list[Document]:
    # Filter documents for list endpoints while preserving cursor ordering.
    settings = get_settings()
    if not documents:
        return []
    principal_attrs = await load_principal_attributes(session=session, principal=principal, commit=False)
    doc_ids = [doc.id for doc in documents]
    labels_map = await _load_document_labels(
        session=session,
        tenant_id=principal.tenant_id,
        document_ids=doc_ids,
    )
    permissions_map = await load_document_permissions_for_principal(
        session=session,
        principal=principal,
        document_ids=doc_ids,
        now=_utc_now(),
    )

    filtered: list[Document] = []
    for doc in documents:
        if doc.tenant_id != principal.tenant_id:
            continue
        if settings.authz_admin_bypass_document_acl and principal.role == "admin":
            acl_allowed = True
        else:
            acl_allowed = document_acl_allows(permissions=permissions_map.get(doc.id), action=action)
        if not acl_allowed:
            continue
        context = await build_document_context(
            session=session,
            principal=principal,
            document=doc,
            request=request,
            principal_attrs=principal_attrs,
            labels=labels_map.get(doc.id, {}),
        )
        decision = await evaluate_policies(
            session=session,
            tenant_id=principal.tenant_id,
            resource_type="document",
            action=action,
            context=context,
            include_trace=False,
        )
        if decision.allowed:
            filtered.append(doc)
    return filtered


async def authorize_document_action(
    *,
    session: AsyncSession,
    principal: Principal,
    document: Document,
    action: str,
    request: Any | None,
) -> None:
    # Apply the full document authorization decision order with auditing.
    if document.tenant_id != principal.tenant_id:
        await _record_access_denied(
            session=session,
            principal=principal,
            request=request,
            reason="tenant_mismatch",
            resource_id=document.id,
            resource_type="document",
            action=action,
        )
        raise _authz_denied("Tenant mismatch")

    now = _utc_now()
    if not await evaluate_document_permissions(
        session=session,
        principal=principal,
        document_id=document.id,
        action=action,
        now=now,
    ):
        if not (get_settings().authz_admin_bypass_document_acl and principal.role == "admin"):
            await _record_access_denied(
                session=session,
                principal=principal,
                request=request,
                reason="document_acl_denied",
                resource_id=document.id,
                resource_type="document",
                action=action,
            )
            raise _authz_denied("Document permission required")

    context = await build_document_context(
        session=session,
        principal=principal,
        document=document,
        request=request,
    )
    decision = await evaluate_policies(
        session=session,
        tenant_id=principal.tenant_id,
        resource_type="document",
        action=action,
        context=context,
        include_trace=False,
    )
    await _record_policy_evaluation(
        session=session,
        principal=principal,
        request=request,
        resource_id=document.id,
        action=action,
        decision=decision,
    )
    if not decision.allowed:
        await _record_access_denied(
            session=session,
            principal=principal,
            request=request,
            reason=decision.reason,
            resource_id=document.id,
            resource_type="document",
            action=action,
        )
        raise _authz_denied("Access denied by policy")


async def authorize_corpus_action(
    *,
    session: AsyncSession,
    principal: Principal,
    corpus_id: str,
    action: str,
    request: Any | None,
) -> None:
    # Apply ABAC policies to corpus-scoped actions such as run.
    context = {
        "principal": {
            "id": principal.subject_id,
            "tenant_id": principal.tenant_id,
            "role": principal.role,
            "auth_method": principal.auth_method,
        },
        "resource": {"id": corpus_id, "tenant_id": principal.tenant_id},
        "request": {"time": _utc_now().isoformat()},
    }
    decision = await evaluate_policies(
        session=session,
        tenant_id=principal.tenant_id,
        resource_type="corpus",
        action=action,
        context=context,
        include_trace=False,
    )
    await _record_policy_evaluation(
        session=session,
        principal=principal,
        request=request,
        resource_id=corpus_id,
        action=action,
        decision=decision,
    )
    if not decision.allowed:
        await _record_access_denied(
            session=session,
            principal=principal,
            request=request,
            reason=decision.reason,
            resource_id=corpus_id,
            resource_type="corpus",
            action=action,
        )
        raise _authz_denied("Access denied by policy")


async def authorize_document_create(
    *,
    session: AsyncSession,
    principal: Principal,
    corpus_id: str,
    labels: dict[str, str] | None,
    request: Any | None,
) -> None:
    # Apply ABAC policies to document creation requests.
    context = {
        "principal": {
            "id": principal.subject_id,
            "tenant_id": principal.tenant_id,
            "role": principal.role,
            "auth_method": principal.auth_method,
        },
        "resource": {
            "id": None,
            "tenant_id": principal.tenant_id,
            "corpus_id": corpus_id,
            "labels": labels or {},
        },
        "request": {"time": _utc_now().isoformat()},
    }
    decision = await evaluate_policies(
        session=session,
        tenant_id=principal.tenant_id,
        resource_type="document",
        action="write",
        context=context,
        include_trace=False,
    )
    await _record_policy_evaluation(
        session=session,
        principal=principal,
        request=request,
        resource_id=corpus_id,
        action="write",
        decision=decision,
    )
    if not decision.allowed:
        await _record_access_denied(
            session=session,
            principal=principal,
            request=request,
            reason=decision.reason,
            resource_id=corpus_id,
            resource_type="document",
            action="write",
        )
        raise _authz_denied("Access denied by policy")


async def _fetch_plan_id(*, session: AsyncSession, tenant_id: str) -> str | None:
    # Resolve the current tenant plan for ABAC context enrichment.
    result = await session.execute(
        select(TenantPlanAssignment.plan_id).where(
            TenantPlanAssignment.tenant_id == tenant_id,
            TenantPlanAssignment.is_active.is_(True),
        )
    )
    row = result.first()
    return row[0] if row else None


async def _fetch_groups(*, session: AsyncSession, tenant_id: str, user_id: str) -> list[str]:
    # Load SCIM group display names for ABAC group checks.
    result = await session.execute(
        select(ScimGroup.display_name)
        .join(ScimGroupMembership, ScimGroupMembership.group_id == ScimGroup.id)
        .where(
            ScimGroupMembership.user_id == user_id,
            ScimGroup.tenant_id == tenant_id,
        )
    )
    return [row[0] for row in result.fetchall() if row[0]]


async def _load_document_labels(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_ids: list[str],
) -> dict[str, dict[str, str]]:
    # Return document labels keyed by document id for ABAC evaluation.
    if not document_ids:
        return {}
    result = await session.execute(
        select(DocumentLabel).where(
            tenant_predicate(DocumentLabel, tenant_id),
            DocumentLabel.document_id.in_(document_ids),
        )
    )
    mapping: dict[str, dict[str, str]] = {}
    for row in result.scalars().all():
        mapping.setdefault(row.document_id, {})[row.key] = row.value
    return mapping


async def _record_policy_evaluation(
    *,
    session: AsyncSession,
    principal: Principal,
    request: Any | None,
    resource_id: str,
    action: str,
    decision: AbacDecision,
) -> None:
    # Emit policy evaluation events without leaking resource payloads.
    request_ctx = get_request_context(request)
    await record_event(
        session=None,
        tenant_id=principal.tenant_id,
        actor_type=principal.auth_method,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="authz.policy.evaluate",
        outcome="success" if decision.allowed else "failure",
        resource_type="policy_eval",
        resource_id=resource_id,
        request_id=request_ctx.get("request_id"),
        ip_address=request_ctx.get("ip_address"),
        user_agent=request_ctx.get("user_agent"),
        metadata={
            "action": action,
            "matched_policy_id": decision.matched_policy_id,
            "reason": decision.reason,
        },
        commit=True,
        best_effort=True,
    )
    if not decision.allowed:
        await record_event(
            session=None,
            tenant_id=principal.tenant_id,
            actor_type=principal.auth_method,
            actor_id=principal.api_key_id,
            actor_role=principal.role,
            event_type="authz.policy.denied",
            outcome="failure",
            resource_type="policy_eval",
            resource_id=resource_id,
            request_id=request_ctx.get("request_id"),
            ip_address=request_ctx.get("ip_address"),
            user_agent=request_ctx.get("user_agent"),
            metadata={
                "action": action,
                "matched_policy_id": decision.matched_policy_id,
                "reason": decision.reason,
            },
            commit=True,
            best_effort=True,
        )


async def _record_access_denied(
    *,
    session: AsyncSession,
    principal: Principal,
    request: Any | None,
    reason: str,
    resource_id: str,
    resource_type: str,
    action: str,
) -> None:
    # Emit access denied events for downstream auditing.
    request_ctx = get_request_context(request)
    await record_event(
        session=None,
        tenant_id=principal.tenant_id,
        actor_type=principal.auth_method,
        actor_id=principal.api_key_id,
        actor_role=principal.role,
        event_type="authz.access.denied",
        outcome="failure",
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_ctx.get("request_id"),
        ip_address=request_ctx.get("ip_address"),
        user_agent=request_ctx.get("user_agent"),
        metadata={"action": action, "reason": reason},
        commit=True,
        best_effort=True,
    )
