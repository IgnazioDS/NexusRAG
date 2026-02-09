from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Checkpoint, Corpus, Message, Session
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key


@pytest.mark.asyncio
async def test_run_stream_emits_seq_and_heartbeat(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("RUN_SSE_HEARTBEAT_S", "1")
    get_settings.cache_clear()

    async def stub_run_graph(**_kwargs):  # type: ignore[override]
        await asyncio.sleep(1.2)
        return {
            "answer": "hello",
            "citations": [],
            "checkpoint_state": {},
        }

    from nexusrag.apps.api.routes import run as run_module

    monkeypatch.setattr(run_module, "run_graph", stub_run_graph)

    app = create_app()
    session_id = f"s-sse-{uuid4()}"
    corpus_id = f"c-sse-{uuid4()}"
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="reader",
    )
    payload = {
        "session_id": session_id,
        "corpus_id": corpus_id,
        "message": "Hello",
        "top_k": 3,
        "audio": False,
    }

    async with SessionLocal() as session:
        session.add(
            Corpus(
                id=corpus_id,
                tenant_id="t1",
                name="SSE Corpus",
                provider_config_json={"retrieval": {"provider": "local_pgvector", "top_k_default": 5}},
            )
        )
        await session.commit()

    events: list[tuple[str, dict]] = []
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/v1/run", json=payload, headers=headers) as response:
                assert response.status_code == 200
                current_event = "message"
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        payload_json = json.loads(line.removeprefix("data: ").strip())
                        events.append((current_event, payload_json))
                        if payload_json.get("type") == "done":
                            break

        seqs = [payload["seq"] for _, payload in events if "seq" in payload]
        assert seqs == sorted(seqs)
        assert any(event_name == "heartbeat" for event_name, _ in events)
        typed = [payload for _, payload in events if payload.get("type")]
        assert typed[0]["type"] == "request.accepted"
        assert typed[-1]["type"] == "done"
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(Checkpoint).where(Checkpoint.session_id == session_id))
            await session.execute(delete(Message).where(Message.session_id == session_id))
            await session.execute(delete(Session).where(Session.id == session_id))
            await session.execute(delete(Corpus).where(Corpus.id == corpus_id))
            await session.commit()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_run_resume_unsupported_event(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()

    app = create_app()
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="reader",
    )
    payload = {
        "session_id": f"s-resume-{uuid4()}",
        "corpus_id": f"c-resume-{uuid4()}",
        "message": "Hello",
        "top_k": 3,
        "audio": False,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/v1/run",
            json=payload,
            headers={**headers, "Last-Event-ID": "5"},
        ) as response:
            assert response.status_code == 200
            current_event = "message"
            first_payload = None
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    first_payload = json.loads(line.removeprefix("data: ").strip())
                    break

    assert first_payload is not None
    assert current_event == "message"
    assert first_payload["type"] == "resume.unsupported"
    assert first_payload.get("seq")
    get_settings.cache_clear()
