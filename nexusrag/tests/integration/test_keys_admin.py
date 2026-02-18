from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from nexusrag.apps.api.main import create_app
from nexusrag.domain.models import PlatformKey
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key


@pytest.mark.asyncio
async def test_platform_key_rotate_list_retire_flow() -> None:
    tenant_id = f"t-keys-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        rotated = await client.post("/v1/admin/keys/rotate?purpose=signing", headers=headers)
        assert rotated.status_code == 200
        payload = rotated.json()["data"]
        assert payload["key"]["purpose"] == "signing"
        assert payload["key"]["status"] == "active"
        assert payload["secret"]

        listed = await client.get("/v1/admin/keys?purpose=signing", headers=headers)
        assert listed.status_code == 200
        rows = listed.json()["data"]
        assert any(row["key_id"] == payload["key"]["key_id"] for row in rows)

        retired = await client.post(f"/v1/admin/keys/{payload['key']['key_id']}/retire", headers=headers)
        assert retired.status_code == 200
        assert retired.json()["data"]["status"] == "retired"


@pytest.mark.asyncio
async def test_keyring_contract_alias_and_encrypted_storage() -> None:
    tenant_id = f"t-keyring-{uuid4().hex}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id=tenant_id,
        role="admin",
        plan_id="enterprise",
    )
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        rotated = await client.post("/v1/admin/keyring/rotate?purpose=backup_signing", headers=headers)
        assert rotated.status_code == 200
        payload = rotated.json()["data"]
        assert payload["key"]["purpose"] == "backup_signing"
        assert payload["key"]["activated_at"] is not None
        assert payload["secret"]

        listed = await client.get("/v1/admin/keyring?purpose=backup_signing", headers=headers)
        assert listed.status_code == 200
        rows = listed.json()["data"]
        assert any(row["key_id"] == payload["key"]["key_id"] for row in rows)

    async with SessionLocal() as session:
        row = (
            await session.execute(select(PlatformKey).where(PlatformKey.key_id == payload["key"]["key_id"]))
        ).scalar_one()
        # Persist only ciphertext so database state never contains the returned plaintext secret.
        assert row.secret_ciphertext != payload["secret"]
        assert payload["secret"] not in row.secret_ciphertext
