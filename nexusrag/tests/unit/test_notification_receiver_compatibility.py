from __future__ import annotations

from pathlib import Path
import json
from uuid import uuid4

import httpx
import pytest

from nexusrag.apps.notify_receiver.app import ReceiverSettings, create_app
from nexusrag.services.notifications.receiver_contract import compute_signature


def _load_profiles() -> list[dict]:
    # Keep compatibility scenarios fixture-driven so matrix updates remain declarative and deterministic.
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "notification_receiver_compatibility.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return list(payload.get("profiles", []))


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", _load_profiles(), ids=lambda item: str(item.get("name")))
async def test_notification_receiver_compatibility_profiles(tmp_path: Path, profile: dict) -> None:
    # Emulate common receiver modes from fixture profiles to prevent contract drift across integrations.
    settings = ReceiverSettings(
        shared_secret=profile["settings"]["shared_secret"],
        require_signature=bool(profile["settings"]["require_signature"]),
        require_timestamp=False,
        max_timestamp_skew_seconds=300,
        fail_mode=str(profile["settings"]["fail_mode"]),
        fail_n=int(profile["settings"]["fail_n"]),
        port=9001,
        store_path=str(tmp_path / f"compat-{uuid4().hex}.db"),
        store_raw_body=False,
    )
    app = create_app(settings)
    body = b'{"event":"incident.opened"}'
    headers = {
        "X-Notification-Id": uuid4().hex,
        "X-Notification-Attempt": "1",
        "X-Notification-Event-Type": "incident.opened",
        "X-Notification-Tenant-Id": "t-compat",
    }
    if bool(profile["request"]["signed"]):
        headers["X-Notification-Signature"] = compute_signature(body, "compat-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://receiver.local") as client:
        response = await client.post("/webhook", content=body, headers=headers)
        stats_response = await client.get("/stats")
        ops_response = await client.get("/ops")
    assert response.status_code == int(profile["expected_status"])
    assert stats_response.status_code == 200
    assert ops_response.status_code == 200
    assert int(stats_response.json()["total_requests"]) >= 1
