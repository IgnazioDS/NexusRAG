from __future__ import annotations

from dataclasses import dataclass

from nexusrag.core.config import get_settings


@dataclass(frozen=True)
class TenantPredicateError(RuntimeError):
    # Surface missing tenant predicates when guard enforcement is enabled.
    message: str


def require_tenant_id(tenant_id: str | None) -> None:
    # Enforce non-empty tenant identifiers when tenant guard checks are enabled.
    settings = get_settings()
    if not settings.authz_require_tenant_predicate:
        return
    if not tenant_id:
        raise TenantPredicateError("Tenant predicate required but tenant_id is missing")


def tenant_predicate(model, tenant_id: str) -> object:
    # Build tenant predicates through a single helper to guarantee guard coverage.
    require_tenant_id(tenant_id)
    return model.tenant_id == tenant_id
