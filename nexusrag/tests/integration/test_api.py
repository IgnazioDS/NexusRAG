from __future__ import annotations

import json
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Checkpoint, Message, Session
from nexusrag.persistence.db import SessionLocal


@pytest.mark.asyncio
async def test_health() -> None:
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_run_emits_error_when_vertex_missing(monkeypatch) -> None:
    # Force missing Vertex configuration to validate error mapping without external calls.
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    # Clear settings cache so the application reads the updated environment.
    get_settings.cache_clear()

    app = create_app()

    session_id = f"s1-{uuid4()}"
    # Track error emission to ensure the stream emits a failure event.
    seen_error = False
    payload = {
        "session_id": session_id,
        "tenant_id": "t1",
        "corpus_id": "c1",
        "message": "Hello?",
        "top_k": 3,
        "audio": False,
    }

    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            async with client.stream("POST", "/run", json=payload) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                lines = []
                async for line in response.aiter_lines():
                if line:
                    lines.append(line)
                if len(lines) >= 2:
                    break

        # Validate SSE framing invariants: event line then data line.
        assert lines[0].startswith("event: message")
        assert lines[1].startswith("data: ")
        payload_json = json.loads(lines[1].removeprefix("data: ").strip())
        assert payload_json["type"] == "error"
        assert payload_json["data"]["code"] == "VERTEX_CONFIG_MISSING"
        seen_error = True
        # Session id should be echoed for traceability during debugging.
        assert payload_json["session_id"] == session_id
        assert payload_json.get("request_id")
        # Request ID should be a non-empty string for tracing.
        assert isinstance(payload_json["request_id"], str)
        assert payload_json["request_id"]

        async with SessionLocal() as db_session:
            # Ensure the session row exists and tenant_id is preserved.
            result = await db_session.execute(select(Session).where(Session.id == session_id))
            session_row = result.scalar_one()
            assert session_row.tenant_id == "t1"
            assert session_row.last_seen_at is not None

            # Verify persistence boundaries: user message only, no assistant message.
            result = await db_session.execute(select(Message).where(Message.session_id == session_id))
            messages = list(result.scalars().all())
            assert len([m for m in messages if m.role == "user"]) == 1
            assert len([m for m in messages if m.role == "assistant"]) == 0
    finally:
        assert seen_error
        # Clean up demo rows to keep the shared test database tidy.
        async with SessionLocal() as db_session:
            await db_session.execute(delete(Checkpoint).where(Checkpoint.session_id == session_id))
            await db_session.execute(delete(Message).where(Message.session_id == session_id))
            await db_session.execute(delete(Session).where(Session.id == session_id))
            await db_session.commit()
