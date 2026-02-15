from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusrag.core.config import get_settings
from nexusrag.domain.models import PolicyRule


POLICY_ACTION_ALLOW = "allow"
POLICY_ACTION_DENY = "deny"
POLICY_ACTION_REDACT_FIELDS = "redact_fields"
POLICY_ACTION_REQUIRE_APPROVAL = "require_approval"
POLICY_ACTION_FORCE_LEGAL_HOLD_CHECK = "force_legal_hold_check"
POLICY_ACTION_REQUIRE_ENCRYPTION = "require_encryption"


@dataclass(frozen=True)
class PolicyDecision:
    # Return a deterministic policy resolution used by endpoint guards.
    allowed: bool
    action: str
    rule_id: int | None
    message: str | None
    code: str | None
    redact_fields: tuple[str, ...]
    require_approval: bool
    force_legal_hold_check: bool
    require_encryption: bool


def _normalize_actions(action_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    # Accept compact or expanded action definitions while preserving order.
    if not isinstance(action_json, dict):
        return [{"type": POLICY_ACTION_ALLOW}]
    if "actions" in action_json and isinstance(action_json["actions"], list):
        actions: list[dict[str, Any]] = []
        for item in action_json["actions"]:
            if isinstance(item, str):
                actions.append({"type": item})
            elif isinstance(item, dict):
                actions.append(item)
        return actions or [{"type": POLICY_ACTION_ALLOW}]
    if "type" in action_json:
        return [action_json]
    # Backward-compatible shorthand: {"deny": true}.
    for key in (
        POLICY_ACTION_DENY,
        POLICY_ACTION_ALLOW,
        POLICY_ACTION_REDACT_FIELDS,
        POLICY_ACTION_REQUIRE_APPROVAL,
        POLICY_ACTION_FORCE_LEGAL_HOLD_CHECK,
        POLICY_ACTION_REQUIRE_ENCRYPTION,
    ):
        if action_json.get(key):
            return [{"type": key, **action_json}]
    return [{"type": POLICY_ACTION_ALLOW}]


def _matches_condition(condition_json: dict[str, Any] | None, context: dict[str, Any]) -> bool:
    # Evaluate a small deterministic DSL to keep policy behavior predictable.
    if not condition_json:
        return True

    endpoint = str(context.get("endpoint") or "")
    method = str(context.get("method") or "").upper()
    tags = {str(value) for value in (context.get("tags") or [])}

    for key, value in condition_json.items():
        if key == "endpoint_prefix":
            if not endpoint.startswith(str(value)):
                return False
            continue
        if key == "endpoint":
            if endpoint != str(value):
                return False
            continue
        if key == "method":
            if method != str(value).upper():
                return False
            continue
        if key == "actor_role_in":
            allowed = {str(item) for item in (value or [])}
            if str(context.get("actor_role") or "") not in allowed:
                return False
            continue
        if key == "tags_any":
            required = {str(item) for item in (value or [])}
            if required and not (tags & required):
                return False
            continue
        # Generic equality match for other context attributes.
        if context.get(key) != value:
            return False
    return True


def redact_context_fields(context: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    # Apply policy-driven redactions to metadata prior to audit writes.
    redacted = dict(context)
    for field in fields:
        if field in redacted:
            redacted[field] = "[REDACTED]"
    return redacted


async def evaluate_policy(
    *,
    session: AsyncSession,
    tenant_id: str | None,
    rule_key: str,
    context: dict[str, Any],
) -> PolicyDecision:
    # Evaluate highest-priority matching rule; default to allow.
    settings = get_settings()
    if not settings.governance_policy_engine_enabled:
        return PolicyDecision(
            allowed=True,
            action=POLICY_ACTION_ALLOW,
            rule_id=None,
            message=None,
            code=None,
            redact_fields=(),
            require_approval=False,
            force_legal_hold_check=False,
            require_encryption=False,
        )

    query = (
        select(PolicyRule)
        .where(
            PolicyRule.enabled.is_(True),
            PolicyRule.rule_key == rule_key,
            or_(PolicyRule.tenant_id == tenant_id, PolicyRule.tenant_id.is_(None)),
        )
        .order_by(
            PolicyRule.priority.desc(),
            # Tie-break on id for stable and deterministic ordering.
            PolicyRule.id.asc(),
        )
    )
    rules = (await session.execute(query)).scalars().all()
    for rule in rules:
        if not _matches_condition(rule.condition_json, context):
            continue
        actions = _normalize_actions(rule.action_json)
        allow = True
        decision_action = POLICY_ACTION_ALLOW
        message: str | None = None
        code: str | None = None
        redact_fields: list[str] = []
        require_approval = False
        force_legal_hold_check = False
        require_encryption = False
        for action in actions:
            action_type = str(action.get("type") or POLICY_ACTION_ALLOW)
            if action_type == POLICY_ACTION_DENY:
                allow = False
                decision_action = POLICY_ACTION_DENY
                message = str(action.get("message") or "Request denied by governance policy")
                code = str(action.get("code") or "POLICY_DENIED")
            elif action_type == POLICY_ACTION_REDACT_FIELDS:
                decision_action = POLICY_ACTION_REDACT_FIELDS
                raw_fields = action.get("fields") or action.get("redact_fields") or []
                redact_fields.extend(str(field) for field in raw_fields)
            elif action_type == POLICY_ACTION_REQUIRE_APPROVAL:
                decision_action = POLICY_ACTION_REQUIRE_APPROVAL
                require_approval = True
                message = str(action.get("message") or "Approval required by governance policy")
                code = str(action.get("code") or "DSAR_REQUIRES_APPROVAL")
            elif action_type == POLICY_ACTION_FORCE_LEGAL_HOLD_CHECK:
                decision_action = POLICY_ACTION_FORCE_LEGAL_HOLD_CHECK
                force_legal_hold_check = True
            elif action_type == POLICY_ACTION_REQUIRE_ENCRYPTION:
                decision_action = POLICY_ACTION_REQUIRE_ENCRYPTION
                require_encryption = True
            else:
                decision_action = POLICY_ACTION_ALLOW
        return PolicyDecision(
            allowed=allow,
            action=decision_action,
            rule_id=rule.id,
            message=message,
            code=code,
            redact_fields=tuple(dict.fromkeys(redact_fields)),
            require_approval=require_approval,
            force_legal_hold_check=force_legal_hold_check,
            require_encryption=require_encryption,
        )

    return PolicyDecision(
        allowed=True,
        action=POLICY_ACTION_ALLOW,
        rule_id=None,
        message=None,
        code=None,
        redact_fields=(),
        require_approval=False,
        force_legal_hold_check=False,
        require_encryption=False,
    )
