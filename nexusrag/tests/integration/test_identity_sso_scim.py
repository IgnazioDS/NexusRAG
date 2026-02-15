from __future__ import annotations

from urllib.parse import urlparse, parse_qs
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api.main import create_app
from nexusrag.apps.api.routes import sso as sso_routes
from nexusrag.core.config import get_settings
from nexusrag.domain.models import (
    IdentityProvider,
    ScimGroup,
    ScimGroupMembership,
    ScimIdentity,
    ScimToken,
    SsoSession,
    TenantUser,
)
from nexusrag.persistence.db import SessionLocal
from nexusrag.services.auth import oidc
from nexusrag.tests.utils.auth import create_test_api_key


def _apply_env(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_DEV_BYPASS", "true")
    monkeypatch.setenv("SSO_ENABLED", "true")
    monkeypatch.setenv("SCIM_ENABLED", "true")
    get_settings.cache_clear()


async def _create_provider(tenant_id: str, jit_enabled: bool = True) -> IdentityProvider:
    provider = IdentityProvider(
        id=uuid4().hex,
        tenant_id=tenant_id,
        type="oidc",
        name="Test OIDC",
        issuer="https://issuer.example",
        client_id="client-123",
        client_secret_ref="OIDC_SECRET",
        auth_url="https://issuer.example/auth",
        token_url="https://issuer.example/token",
        jwks_url="https://issuer.example/jwks",
        scopes_json=["openid"],
        enabled=True,
        default_role="reader",
        role_mapping_json={"groups": {"Admins": "admin"}},
        jit_enabled=jit_enabled,
    )
    async with SessionLocal() as session:
        session.add(provider)
        await session.commit()
    return provider


async def _cleanup_identity(tenant_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(ScimGroupMembership))
        await session.execute(delete(ScimGroup).where(ScimGroup.tenant_id == tenant_id))
        await session.execute(delete(ScimIdentity).where(ScimIdentity.tenant_id == tenant_id))
        await session.execute(delete(ScimToken).where(ScimToken.tenant_id == tenant_id))
        await session.execute(delete(SsoSession).where(SsoSession.tenant_id == tenant_id))
        await session.execute(delete(TenantUser).where(TenantUser.tenant_id == tenant_id))
        await session.execute(delete(IdentityProvider).where(IdentityProvider.tenant_id == tenant_id))
        await session.commit()


@pytest.mark.asyncio
async def test_sso_callback_success_creates_user(monkeypatch) -> None:
    # Validate SSO callback creates tenant users and sessions.
    tenant_id = f"t-sso-{uuid4().hex}"
    _apply_env(monkeypatch)
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    provider = await _create_provider(tenant_id)

    async def _fake_exchange(**_kwargs):
        return oidc.OidcTokenResponse(id_token="token", access_token=None, token_type=None, expires_in=None)

    async def _fake_validate(**_kwargs):
        return {"sub": "sub-1", "email": "user@example.com", "name": "User One"}

    monkeypatch.setattr(sso_routes, "exchange_code_for_tokens", _fake_exchange)
    monkeypatch.setattr(sso_routes, "validate_id_token", _fake_validate)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start = await client.get(f"/v1/auth/sso/oidc/{provider.id}/start")
        assert start.status_code == 200
        authorize_url = start.json()["data"]["authorize_url"]
        parsed = urlparse(authorize_url)
        state = parse_qs(parsed.query)["state"][0]

        callback = await client.get(
            f"/v1/auth/sso/oidc/{provider.id}/callback",
            params={"code": "test-code", "state": state},
        )
        assert callback.status_code == 200
        payload = callback.json()["data"]
        assert payload["session_token"].startswith("nrgss_")

    async with SessionLocal() as session:
        result = await session.execute(
            select(TenantUser).where(TenantUser.tenant_id == tenant_id)
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.external_subject == "sub-1"

    await _cleanup_identity(tenant_id)


@pytest.mark.asyncio
async def test_sso_invalid_state_returns_error(monkeypatch) -> None:
    # Return SSO_INVALID_STATE when state is missing or invalid.
    tenant_id = f"t-sso-invalid-{uuid4().hex}"
    _apply_env(monkeypatch)
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="enterprise")
    provider = await _create_provider(tenant_id)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/v1/auth/sso/oidc/{provider.id}/callback",
            params={"code": "test", "state": "bad"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "SSO_INVALID_STATE"

    await _cleanup_identity(tenant_id)


@pytest.mark.asyncio
async def test_scim_user_crud_flow(monkeypatch) -> None:
    # Exercise SCIM user create/read/patch/delete flow with token auth.
    tenant_id = f"t-scim-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token_resp = await client.post("/v1/admin/identity/scim/token/create", headers=headers)
        assert token_resp.status_code == 201
        token = token_resp.json()["data"]["token"]
        scim_headers = {"Authorization": f"Bearer {token}"}

        create_payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "user-1",
            "displayName": "User One",
            "emails": [{"value": "user@example.com", "primary": True}],
            "active": True,
        }
        create_resp = await client.post("/v1/scim/v2/Users", json=create_payload, headers=scim_headers)
        assert create_resp.status_code == 201
        user_id = create_resp.json()["data"]["id"]

        get_resp = await client.get(f"/v1/scim/v2/Users/{user_id}", headers=scim_headers)
        assert get_resp.status_code == 200

        patch_payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "displayName", "value": "Updated"}],
        }
        patch_resp = await client.patch(
            f"/v1/scim/v2/Users/{user_id}", json=patch_payload, headers=scim_headers
        )
        assert patch_resp.status_code == 200

        delete_resp = await client.delete(f"/v1/scim/v2/Users/{user_id}", headers=scim_headers)
        assert delete_resp.status_code == 204

    await _cleanup_identity(tenant_id)


@pytest.mark.asyncio
async def test_scim_group_role_binding_affects_role(monkeypatch) -> None:
    # Apply role bindings when SCIM groups update memberships.
    tenant_id = f"t-scim-role-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        token_resp = await client.post("/v1/admin/identity/scim/token/create", headers=headers)
        token = token_resp.json()["data"]["token"]
        scim_headers = {"Authorization": f"Bearer {token}"}

        user_resp = await client.post(
            "/v1/scim/v2/Users",
            json={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": "role-user",
                "displayName": "Role User",
                "emails": [{"value": "role@example.com"}],
                "active": True,
            },
            headers=scim_headers,
        )
        user_id = user_resp.json()["data"]["id"]

    async with SessionLocal() as session:
        group = ScimGroup(
            id=uuid4().hex,
            tenant_id=tenant_id,
            external_id="group-1",
            display_name="Admins",
            role_binding="admin",
        )
        session.add(group)
        await session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        patch_payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "add", "path": "members", "value": [{"value": user_id}]}
            ],
        }
        patch_resp = await client.patch(
            f"/v1/scim/v2/Groups/{group.id}", json=patch_payload, headers=scim_headers
        )
        assert patch_resp.status_code == 200

    async with SessionLocal() as session:
        user = await session.get(TenantUser, user_id)
        assert user is not None
        assert user.role == "admin"

    await _cleanup_identity(tenant_id)


@pytest.mark.asyncio
async def test_entitlement_gating_blocks_sso_and_scim(monkeypatch) -> None:
    # Enforce plan entitlements for SSO and SCIM admin operations.
    tenant_id = f"t-gate-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id, role="admin", plan_id="free"
    )
    provider = await _create_provider(tenant_id)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start = await client.get(f"/v1/auth/sso/oidc/{provider.id}/start")
        assert start.status_code == 403
        assert start.json()["error"]["code"] == "FEATURE_NOT_ENABLED"
        token_resp = await client.post("/v1/admin/identity/scim/token/create", headers=headers)
        assert token_resp.status_code == 403
        assert token_resp.json()["error"]["code"] == "FEATURE_NOT_ENABLED"

    await _cleanup_identity(tenant_id)


@pytest.mark.asyncio
async def test_admin_identity_endpoints_require_admin_role(monkeypatch) -> None:
    # Require admin role for identity management endpoints.
    tenant_id = f"t-admin-{uuid4().hex}"
    _apply_env(monkeypatch)
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="reader",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/identity/providers",
            headers=headers,
            json={
                "type": "oidc",
                "name": "Test",
                "issuer": "https://issuer.example",
                "client_id": "client-123",
                "client_secret_ref": "OIDC_SECRET",
                "auth_url": "https://issuer.example/auth",
                "token_url": "https://issuer.example/token",
                "jwks_url": "https://issuer.example/jwks",
                "scopes_json": ["openid"],
                "default_role": "reader",
                "role_mapping_json": None,
                "jit_enabled": True,
            },
        )
        assert response.status_code == 403

    await _cleanup_identity(tenant_id)


@pytest.mark.asyncio
async def test_jit_entitlement_blocks_provisioning(monkeypatch) -> None:
    # Block JIT provisioning when tenant lacks JIT entitlement.
    tenant_id = f"t-jit-{uuid4().hex}"
    _apply_env(monkeypatch)
    await create_test_api_key(tenant_id=tenant_id, role="admin", plan_id="pro")
    provider = await _create_provider(tenant_id, jit_enabled=True)

    async def _fake_exchange(**_kwargs):
        return oidc.OidcTokenResponse(id_token="token", access_token=None, token_type=None, expires_in=None)

    async def _fake_validate(**_kwargs):
        return {"sub": "sub-1", "email": "user@example.com", "name": "User One"}

    monkeypatch.setattr(sso_routes, "exchange_code_for_tokens", _fake_exchange)
    monkeypatch.setattr(sso_routes, "validate_id_token", _fake_validate)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        start = await client.get(f"/v1/auth/sso/oidc/{provider.id}/start")
        authorize_url = start.json()["data"]["authorize_url"]
        parsed = urlparse(authorize_url)
        state = parse_qs(parsed.query)["state"][0]

        callback = await client.get(
            f"/v1/auth/sso/oidc/{provider.id}/callback",
            params={"code": "test-code", "state": state},
        )
        assert callback.status_code == 403
        assert callback.json()["error"]["code"] == "FEATURE_NOT_ENABLED"

    await _cleanup_identity(tenant_id)
