import base64
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from sg_api.future_self.router import get_user_uuid, get_voice_service
from sg_api.main import create_app
from sg_api.sessions.briefing import StubBriefingProvider, get_briefing_provider
from sg_core.providers.elevenlabs import AudioResult, ElevenLabsError, Transcript
from sg_core.providers.llm import ChatMessage, LLMResponse
from sg_core.providers.storage import InMemoryObjectStore
from sg_core.settings import Environment, Settings, get_settings
from sg_core.voice_clone import FutureSelfVoice, InMemoryConsentStore

SECRET = b"k" * 48
SETTINGS = Settings(  # type: ignore[call-arg]
    _env_file=None, environment=Environment.TEST, agent_tool_token_secret=SecretStr("k" * 48)
)
USER = uuid.uuid4()
AUDIO = b"\x1aE\xdf\xa3" + b"x" * 4096


class FakeEL:
    def __init__(self) -> None:
        self.transcript = ""
        self.voices: set[str] = set()
        self.fail_delete = False

    async def transcribe(self, audio: bytes, **kwargs: object) -> Transcript:
        return Transcript(text=self.transcript)

    async def create_instant_voice_clone(self, **kwargs: object) -> str:
        self.voices.add("v1")
        return "v1"

    async def delete_voice(self, voice_id: str) -> bool:
        if self.fail_delete:
            raise ElevenLabsError(500, "x")
        self.voices.discard(voice_id)
        return True

    async def text_to_speech(self, voice_id: str, text: str, **kwargs: object) -> AudioResult:
        return AudioResult(audio=b"mp3bytes")


class FakeLLM:
    async def complete(self, messages: list[ChatMessage], **kwargs: object) -> LLMResponse:
        return LLMResponse(model="m", content="[warmly] You made it.")


@pytest.fixture
async def ctx() -> AsyncIterator[tuple[AsyncClient, FakeEL]]:
    app = create_app()
    el = FakeEL()
    service = FutureSelfVoice(
        store=InMemoryConsentStore(),
        objects=InMemoryObjectStore(),
        elevenlabs=el,
        secret=SECRET,
        llm=FakeLLM(),
    )
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_user_uuid] = lambda: USER
    app.dependency_overrides[get_voice_service] = lambda: service
    app.dependency_overrides[get_briefing_provider] = StubBriefingProvider
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Dev-User-Id": "user_1"},
    ) as client:
        yield client, el


async def _record(client: AsyncClient, token: str, **over: str) -> object:
    headers = {
        "X-Consent-Challenge": token,
        "X-Consent-Accepted": "true",
        "Content-Type": "audio/webm",
    } | over
    return await client.post("/v1/future-self/consent/recording", content=AUDIO, headers=headers)


async def test_requires_auth() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/v1/future-self/consent")).status_code == 401
        assert (await client.delete("/v1/future-self/consent")).status_code == 401


async def test_consent_clone_message_revoke_flow(ctx: tuple[AsyncClient, FakeEL]) -> None:
    client, el = ctx
    status = (await client.get("/v1/future-self/consent")).json()
    assert status["active"] is False and status["statements"]

    challenge = (await client.post("/v1/future-self/consent/challenge")).json()
    assert challenge["phrase"] and challenge["challenge_token"]
    el.transcript = challenge["phrase"]
    response = await _record(client, challenge["challenge_token"])
    assert response.status_code == 200, response.text  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert body["verified"] is True and body["status"]["active"] is True
    assert el.voices == {"v1"}
    assert "voice_id" not in str(body)  # the provider voice id never reaches the browser

    assert (await client.post("/v1/future-self/consent/challenge")).status_code == 409

    message = await client.post("/v1/future-self/message")
    assert message.status_code == 200, message.text
    assert message.json()["script"] == "[warmly] You made it."
    assert base64.b64decode(message.json()["audio_base64"]) == b"mp3bytes"

    assert (await client.delete("/v1/future-self/consent")).status_code == 204
    assert el.voices == set()
    after = (await client.get("/v1/future-self/consent")).json()
    assert after["active"] is False and after["history"][0]["revoked_at"] is not None
    assert (await client.post("/v1/future-self/message")).status_code == 403
    assert (await client.delete("/v1/future-self/consent")).status_code == 204


async def test_wrong_phrase_is_not_verified(ctx: tuple[AsyncClient, FakeEL]) -> None:
    client, el = ctx
    challenge = (await client.post("/v1/future-self/consent/challenge")).json()
    el.transcript = "someone else talking"
    response = await _record(client, challenge["challenge_token"])
    assert response.status_code == 200  # type: ignore[attr-defined]
    assert response.json()["verified"] is False  # type: ignore[attr-defined]
    assert el.voices == set()


async def test_recording_errors(ctx: tuple[AsyncClient, FakeEL]) -> None:
    client, el = ctx
    challenge = (await client.post("/v1/future-self/consent/challenge")).json()
    el.transcript = challenge["phrase"]
    token = challenge["challenge_token"]
    r = await _record(client, token, **{"X-Consent-Accepted": "false"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"  # type: ignore[attr-defined]
    r = await _record(client, "bad.token")
    assert r.status_code == 400  # type: ignore[attr-defined]
    r = await _record(client, token, **{"Content-Type": "text/plain"})
    assert r.status_code == 422  # type: ignore[attr-defined]


async def test_revoke_provider_failure_is_502_and_retryable(
    ctx: tuple[AsyncClient, FakeEL],
) -> None:
    client, el = ctx
    challenge = (await client.post("/v1/future-self/consent/challenge")).json()
    el.transcript = challenge["phrase"]
    await _record(client, challenge["challenge_token"])
    el.fail_delete = True
    assert (await client.delete("/v1/future-self/consent")).status_code == 502
    assert (await client.get("/v1/future-self/consent")).json()["active"] is True
    el.fail_delete = False
    assert (await client.delete("/v1/future-self/consent")).status_code == 204
