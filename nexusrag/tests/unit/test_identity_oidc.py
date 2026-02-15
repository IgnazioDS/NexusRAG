from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from nexusrag.domain.models import IdentityProvider, TenantUser
from nexusrag.services.auth import oidc


def _make_provider() -> IdentityProvider:
    return IdentityProvider(
        id="prov_1",
        tenant_id="tenant_1",
        type="oidc",
        name="Test",
        issuer="https://issuer.example",
        client_id="client_123",
        client_secret_ref="OIDC_SECRET",
        auth_url="https://issuer.example/auth",
        token_url="https://issuer.example/token",
        jwks_url="https://issuer.example/jwks",
        scopes_json=["openid"],
        enabled=True,
        default_role="reader",
        role_mapping_json={"groups": {"Admins": "admin"}},
        jit_enabled=True,
    )


def _generate_jwks() -> tuple[object, dict]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = "test-kid"
    return private_key, {"keys": [jwk]}


@pytest.mark.asyncio
async def test_id_token_validation_pass(monkeypatch) -> None:
    # Accept tokens with valid issuer, audience, exp, and nonce.
    provider = _make_provider()
    private_key, jwks = _generate_jwks()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "user-1",
        "iss": provider.issuer,
        "aud": provider.client_id,
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": "nonce-1",
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-kid"})

    async def _fake_fetch(_jwks_url: str) -> dict:
        return jwks

    monkeypatch.setattr(oidc, "_fetch_jwks", _fake_fetch)
    decoded = await oidc.validate_id_token(
        provider=provider,
        token=token,
        nonce="nonce-1",
        clock_skew_seconds=0,
    )
    assert decoded["sub"] == "user-1"


@pytest.mark.asyncio
async def test_id_token_validation_rejects_bad_issuer(monkeypatch) -> None:
    # Reject tokens when issuer mismatches the provider config.
    provider = _make_provider()
    private_key, jwks = _generate_jwks()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "user-1",
        "iss": "https://wrong.example",
        "aud": provider.client_id,
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": "nonce-1",
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-kid"})

    async def _fake_fetch(_jwks_url: str) -> dict:
        return jwks

    monkeypatch.setattr(oidc, "_fetch_jwks", _fake_fetch)
    with pytest.raises(Exception):
        await oidc.validate_id_token(
            provider=provider,
            token=token,
            nonce="nonce-1",
            clock_skew_seconds=0,
        )


@pytest.mark.asyncio
async def test_id_token_validation_rejects_expired(monkeypatch) -> None:
    # Reject tokens that are already expired.
    provider = _make_provider()
    private_key, jwks = _generate_jwks()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "user-1",
        "iss": provider.issuer,
        "aud": provider.client_id,
        "exp": int((now - timedelta(minutes=1)).timestamp()),
        "nonce": "nonce-1",
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-kid"})

    async def _fake_fetch(_jwks_url: str) -> dict:
        return jwks

    monkeypatch.setattr(oidc, "_fetch_jwks", _fake_fetch)
    with pytest.raises(Exception):
        await oidc.validate_id_token(
            provider=provider,
            token=token,
            nonce="nonce-1",
            clock_skew_seconds=0,
        )


@pytest.mark.asyncio
async def test_role_mapping_precedence(monkeypatch) -> None:
    # Prefer SCIM-derived roles over claim mapping and defaults.
    provider = _make_provider()
    claims = oidc.OidcClaims(
        subject="user-1",
        email="user@example.com",
        name="User",
        groups=["Admins"],
        raw={"groups": ["Admins"]},
    )

    async def _fake_scim_role(**_kwargs):
        return "editor"

    monkeypatch.setattr(oidc, "resolve_role_from_scim", _fake_scim_role)

    tenant_user = TenantUser(
        id="user-1",
        tenant_id=provider.tenant_id,
        external_subject="user-1",
        email="user@example.com",
        display_name="User",
        status="active",
        role="reader",
        last_login_at=None,
    )

    role = await oidc.resolve_role(
        session=None,
        provider=provider,
        claims=claims,
        tenant_id=provider.tenant_id,
        user=tenant_user,
    )
    assert role == "editor"
