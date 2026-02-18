from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from nexusrag.apps.api.main import create_app
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
