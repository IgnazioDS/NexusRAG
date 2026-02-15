from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from nexusrag.apps.api.main import create_app
from nexusrag.core.config import get_settings
from nexusrag.domain.models import Checkpoint, Corpus, Message, Session
from nexusrag.persistence.db import SessionLocal
from nexusrag.tests.utils.auth import create_test_api_key


@pytest.mark.asyncio
async def test_health() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
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
    corpus_id = f"c1-{uuid4()}"
    # Track error emission to ensure the stream emits a failure event.
    seen_error = False
    # Provision a reader key so /run passes auth for this tenant.
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="reader",
    )
    payload = {
        "session_id": session_id,
        "corpus_id": corpus_id,
        "message": "Hello?",
        "top_k": 3,
        "audio": False,
    }

    try:
        async with SessionLocal() as db_session:
            # Insert a local retrieval config so routing does not fail on missing corpus config.
            db_session.add(
                Corpus(
                    id=corpus_id,
                    tenant_id="t1",
                    name="Test Corpus",
                    provider_config_json={
                        "retrieval": {"provider": "local_pgvector", "top_k_default": 5}
                    },
                )
            )
            await db_session.commit()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/run", json=payload, headers=headers) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                payloads = []
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = json.loads(line.removeprefix("data: ").strip())
                    payloads.append(payload)
                    if payload.get("type") == "error":
                        break

        typed_payloads = [payload for payload in payloads if "type" in payload]
        # Ensure request.accepted is emitted before the error event.
        assert typed_payloads[0]["type"] == "request.accepted"
        assert typed_payloads[1]["type"] == "error"
        payload_json = typed_payloads[1]
        assert payload_json["data"]["code"] == "VERTEX_CONFIG_MISSING"
        seen_error = True
        # Session id should be echoed for traceability during debugging.
        assert payload_json["session_id"] == session_id
        assert payload_json.get("request_id")
        # Request ID should be a non-empty string for tracing.
        assert isinstance(payload_json["request_id"], str)
        assert payload_json["request_id"]
        # Sequence numbers should be present and increasing.
        seqs = [payload["seq"] for payload in typed_payloads]
        assert seqs == sorted(seqs)

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
            await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
            await db_session.commit()


@pytest.mark.asyncio
async def test_run_emits_audio_ready_with_fake_tts(monkeypatch) -> None:
    # Force fake providers to avoid external dependencies.
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("TTS_PROVIDER", "fake")
    monkeypatch.setenv("AUDIO_BASE_URL", "http://test")
    get_settings.cache_clear()

    app = create_app()
    session_id = f"s-audio-{uuid4()}"
    corpus_id = f"c-audio-{uuid4()}"
    # Provision a reader key so /run passes auth for this tenant.
    _raw_key, headers, _user_id, _key_id = await create_test_api_key(
        tenant_id="t1",
        role="reader",
    )
    payload = {
        "session_id": session_id,
        "corpus_id": corpus_id,
        "message": "Hello?",
        "top_k": 3,
        "audio": True,
    }

    audio_id = None
    try:
        async with SessionLocal() as db_session:
            db_session.add(
                Corpus(
                    id=corpus_id,
                    tenant_id="t1",
                    name="Audio Corpus",
                    provider_config_json={
                        "retrieval": {"provider": "local_pgvector", "top_k_default": 5}
                    },
                )
            )
            await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream("POST", "/run", json=payload, headers=headers) as response:
                assert response.status_code == 200
                lines = []
                async for line in response.aiter_lines():
                    if line:
                        lines.append(line)
                    # Stop after we see audio.ready.
                    if any("audio.ready" in l for l in lines):
                        break

            data_lines = [l for l in lines if l.startswith("data: ")]
            assert data_lines
            audio_events = [
                json.loads(l.removeprefix("data: ").strip())
                for l in data_lines
                if "audio.ready" in l
            ]
            assert audio_events
            audio_payload = audio_events[-1]["data"]
            audio_id = audio_payload["audio_id"]
            audio_url = audio_payload["audio_url"]

            settings = get_settings()
            if settings.crypto_enabled:
                path = Path("var") / "audio" / f"{audio_id}.enc"
                assert path.exists()
            else:
                path = Path("var") / "audio" / f"{audio_id}.mp3"
                assert path.exists()

            # Validate the audio route serves the generated file.
            response = await client.get(audio_url)
            assert response.status_code == 200
    finally:
        if audio_id:
            mp3_path = Path("var") / "audio" / f"{audio_id}.mp3"
            enc_path = Path("var") / "audio" / f"{audio_id}.enc"
            if mp3_path.exists():
                mp3_path.unlink()
            if enc_path.exists():
                enc_path.unlink()
        async with SessionLocal() as db_session:
            await db_session.execute(delete(Checkpoint).where(Checkpoint.session_id == session_id))
            await db_session.execute(delete(Message).where(Message.session_id == session_id))
            await db_session.execute(delete(Session).where(Session.id == session_id))
            await db_session.execute(delete(Corpus).where(Corpus.id == corpus_id))
            await db_session.commit()
