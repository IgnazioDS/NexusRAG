from __future__ import annotations

import types

import pytest

from nexusrag.core.errors import AwsAuthError, RetrievalConfigError
import scripts.provider_smoke as provider_smoke


class DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummySessionFactory:
    def __call__(self):
        # Provide an async context manager compatible with SessionLocal().
        return DummySession()


class FailingRouter:
    def __init__(self, _session):
        pass

    async def retrieve(self, *_args, **_kwargs):
        # Trigger a controlled error to validate mapping in the smoke script.
        raise RetrievalConfigError("bad config")


class AuthFailingRouter:
    def __init__(self, _session):
        pass

    async def retrieve(self, *_args, **_kwargs):
        # Simulate an auth failure without hitting a real provider.
        raise AwsAuthError("no creds")


@pytest.mark.asyncio
async def test_provider_smoke_returns_config_error(monkeypatch) -> None:
    monkeypatch.setattr(provider_smoke, "SessionLocal", DummySessionFactory())
    monkeypatch.setattr(provider_smoke, "RetrievalRouter", FailingRouter)

    args = types.SimpleNamespace(tenant="t1", corpus="c1", query="q", top_k=5)
    with pytest.raises(RetrievalConfigError):
        # _run should surface the underlying error for main() to map.
        await provider_smoke._run(args)

    code, message = provider_smoke._format_error(RetrievalConfigError("bad"))
    assert code == 2
    assert "RETRIEVAL_CONFIG_INVALID" in message


@pytest.mark.asyncio
async def test_provider_smoke_returns_auth_error(monkeypatch) -> None:
    monkeypatch.setattr(provider_smoke, "SessionLocal", DummySessionFactory())
    monkeypatch.setattr(provider_smoke, "RetrievalRouter", AuthFailingRouter)

    args = types.SimpleNamespace(tenant="t1", corpus="c1", query="q", top_k=5)
    with pytest.raises(AwsAuthError):
        await provider_smoke._run(args)

    code, message = provider_smoke._format_error(AwsAuthError("no creds"))
    assert code == 3
    assert "AWS_AUTH_ERROR" in message
