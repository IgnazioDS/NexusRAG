from __future__ import annotations

import pytest

from nexusrag.core.config import get_settings
from nexusrag.persistence.guards import TenantPredicateError
from nexusrag.persistence.repos import authz as authz_repo
from nexusrag.persistence.repos import corpora as corpora_repo
from nexusrag.persistence.repos import documents as documents_repo


def _enable_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force tenant predicate enforcement for guard tests.
    monkeypatch.setenv("AUTHZ_REQUIRE_TENANT_PREDICATE", "true")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_document_repo_requires_tenant_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_guard(monkeypatch)
    with pytest.raises(TenantPredicateError):
        await documents_repo.list_documents(None, None)  # type: ignore[arg-type]
    with pytest.raises(TenantPredicateError):
        await documents_repo.get_document(None, None, "doc")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_corpora_repo_requires_tenant_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_guard(monkeypatch)
    with pytest.raises(TenantPredicateError):
        await corpora_repo.list_corpora_by_tenant(None, None)  # type: ignore[arg-type]
    with pytest.raises(TenantPredicateError):
        await corpora_repo.get_corpus_for_tenant(None, "c1", None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_authz_repo_requires_tenant_predicate(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_guard(monkeypatch)
    with pytest.raises(TenantPredicateError):
        await authz_repo.list_policies(None, tenant_id=None)  # type: ignore[arg-type]
    with pytest.raises(TenantPredicateError):
        await authz_repo.get_policy(None, tenant_id=None, policy_id="p1")  # type: ignore[arg-type]
    with pytest.raises(TenantPredicateError):
        await authz_repo.list_document_permissions(None, tenant_id=None, document_id="d1")  # type: ignore[arg-type]
