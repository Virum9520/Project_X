import hashlib
import hmac
import time
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from sg_api.main import create_app
from sg_api.webhooks import router as webhook_router
from sg_core.webhooks import ElevenLabsVerifier, IngestOutcome, IngestResult, VerifierRegistry

SECRET = "whsec_test"
BODY = b'{"type":"post_call_transcription","data":{"conversation_id":"c1"}}'


class FakeDispatcher:
    async def dispatch(self, provider_event_id: uuid.UUID, provider: str, event_type: str) -> None:
        raise AssertionError("must not dispatch unverified events")


def app_with_registry() -> FastAPI:
    app = create_app()
    registry = VerifierRegistry()
    registry.register(ElevenLabsVerifier(SecretStr(SECRET)))
    app.state.webhook_registry = registry
    app.state.webhook_dispatcher = FakeDispatcher()
    return app


async def post(app: FastAPI, provider: str, headers: dict[str, str]) -> int:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/v1/webhooks/{provider}", content=BODY, headers=headers)
    return response.status_code


async def test_bad_signature_is_401_before_any_storage_or_dispatch() -> None:
    app = app_with_registry()
    forged = {"ElevenLabs-Signature": f"t={int(time.time())},v0=00"}
    assert await post(app, "elevenlabs", forged) == 401
    assert await post(app, "elevenlabs", {}) == 401


async def test_unknown_provider_is_404() -> None:
    assert await post(app_with_registry(), "nope", {}) == 404


async def test_valid_signature_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bytes] = []

    async def fake_ingest(*_a: object, body: bytes, **_k: object) -> IngestResult:
        calls.append(body)
        return IngestResult(IngestOutcome.ACCEPTED, uuid.uuid4(), dispatched=True)

    monkeypatch.setattr(webhook_router, "ingest_webhook", fake_ingest)
    ts = int(time.time())
    mac = hmac.new(SECRET.encode(), f"{ts}.".encode() + BODY, hashlib.sha256).hexdigest()
    headers = {"ElevenLabs-Signature": f"t={ts},v0={mac}"}
    assert await post(app_with_registry(), "elevenlabs", headers) == 202
    assert calls == [BODY]
