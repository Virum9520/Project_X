import json
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from sg_api.main import create_app
from sg_api.sessions.router import get_elevenlabs
from sg_api.sessions.tool_tokens import mint_tool_token, verify_tool_token
from sg_core.providers.elevenlabs import ElevenLabsClient
from sg_core.settings import Environment, Settings, get_settings

Handler = Callable[[httpx.Request], httpx.Response]


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "agent_tool_token_secret": SecretStr("x" * 48),
        "elevenlabs_agent_ids": {"drona": "agent_drona"},
    }
    return Settings(_env_file=None, **(values | overrides))  # type: ignore[call-arg]


def _token_ok(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/convai/conversation/token"
    assert request.headers["xi-api-key"] == "xi-test"
    assert request.url.params["agent_id"] == "agent_drona"
    return httpx.Response(200, json={"token": "lk_token", "conversation_id": "conv_123"})


def _app(settings: Settings, handler: Handler = _token_ok) -> AsyncClient:
    app = create_app()

    async def fake_elevenlabs() -> AsyncIterator[ElevenLabsClient]:
        async with ElevenLabsClient(
            SecretStr("xi-test"), transport=httpx.MockTransport(handler)
        ) as client:
            yield client

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_elevenlabs] = fake_elevenlabs
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


DYNAMIC_VARIABLES = Path(__file__).resolve().parents[3] / "agents" / "dynamic_variables.yaml"
DEV_HEADERS = {"X-Dev-User-Id": "user_1", "X-Dev-User-Name": "Asha"}


async def test_start_session_returns_token_and_dynamic_variables() -> None:
    settings = _settings()
    async with _app(settings) as client:
        response = await client.post(
            "/v1/sessions",
            json={"character": "drona", "focus_concept_id": "dsa.binary_search"},
            headers=DEV_HEADERS,
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["conversation_token"] == "lk_token"
    assert body["conversation_id"] == "conv_123"
    assert body["agent_id"] == "agent_drona"
    variables = body["dynamic_variables"]
    assert variables["learner_name"] == "Asha"
    assert variables["focus_concept"] == "dsa.binary_search"
    assert variables["session_id"] == body["session_id"]
    assert all(isinstance(v, str) for v in variables.values())

    claims = verify_tool_token(variables["secret__sg_tool_token"], settings)
    assert claims.user_id == "user_1"
    assert claims.session_id == body["session_id"]
    assert claims.conversation_id == "conv_123"
    assert claims.character == "drona"


async def test_dynamic_variables_cover_every_declared_agent_variable() -> None:
    declared = set(yaml.safe_load(DYNAMIC_VARIABLES.read_text()))
    async with _app(_settings()) as client:
        response = await client.post(
            "/v1/sessions", json={"character": "drona"}, headers=DEV_HEADERS
        )
    assert set(response.json()["dynamic_variables"]) == declared


async def test_unconfigured_agent_is_503() -> None:
    async with _app(_settings(elevenlabs_agent_ids={})) as client:
        response = await client.post(
            "/v1/sessions", json={"character": "drona"}, headers=DEV_HEADERS
        )
    assert response.status_code == 503


async def test_provider_failure_is_502() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with _app(_settings(), fail) as client:
        response = await client.post(
            "/v1/sessions", json={"character": "drona"}, headers=DEV_HEADERS
        )
    assert response.status_code == 502


async def test_dev_identity_requires_header() -> None:
    async with _app(_settings()) as client:
        response = await client.post("/v1/sessions", json={"character": "drona"})
    assert response.status_code == 401


@pytest.mark.parametrize("environment", [Environment.DEV, Environment.PROD])
async def test_dev_headers_are_ignored_outside_local(environment: Environment) -> None:
    async with _app(_settings(environment=environment)) as client:
        response = await client.post(
            "/v1/sessions", json={"character": "drona"}, headers=DEV_HEADERS
        )
    assert response.status_code == 401


async def test_clerk_session_identifies_the_learner() -> None:
    from sg_core.identity import InvalidTokenError, SessionClaims

    class FakeVerifier:
        async def verify(self, token: str) -> SessionClaims:
            if token != "good":
                raise InvalidTokenError("bad token")
            return SessionClaims(
                user_id="user_clerk",
                session_id="sess_1",
                authorized_party=None,
                expires_at=int(time.time()) + 60,
                factor_verification_age=(1, -1),
            )

    settings = _settings(environment=Environment.PROD)
    async with _app(settings) as client:
        client._transport.app.state.identity.verifier = FakeVerifier()  # type: ignore[attr-defined]
        ok = await client.post(
            "/v1/sessions", json={"character": "drona"}, headers={"Authorization": "Bearer good"}
        )
        bad = await client.post(
            "/v1/sessions", json={"character": "drona"}, headers={"Authorization": "Bearer nope"}
        )
    assert ok.status_code == 201, ok.text
    claims = verify_tool_token(ok.json()["dynamic_variables"]["secret__sg_tool_token"], settings)
    assert claims.user_id == "user_clerk"
    assert bad.status_code == 401


async def test_unknown_character_is_rejected() -> None:
    async with _app(_settings()) as client:
        response = await client.post(
            "/v1/sessions", json={"character": "owner_assistant"}, headers=DEV_HEADERS
        )
    assert response.status_code == 422


def test_tool_token_rejects_expired_and_foreign_tokens() -> None:
    from fastapi import HTTPException

    settings = _settings()
    token, _ = mint_tool_token(
        user_id="u",
        session_id="s",
        character="drona",
        conversation_id="c",
        settings=settings,
        now=int(time.time()) - 2 * settings.agent_tool_token_ttl_seconds,
    )
    with pytest.raises(HTTPException) as expired:
        verify_tool_token(token, settings)
    assert expired.value.status_code == 401

    other = _settings(agent_tool_token_secret=SecretStr("y" * 48))
    fresh, _ = mint_tool_token(
        user_id="u", session_id="s", character="drona", conversation_id="c", settings=other
    )
    with pytest.raises(HTTPException):
        verify_tool_token(fresh, settings)


def test_agent_ids_parse_from_env_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_AGENT_IDS", json.dumps({"drona": "agent_x"}))
    assert Settings(_env_file=None).elevenlabs_agent_ids == {"drona": "agent_x"}  # type: ignore[call-arg]


def test_tool_token_is_bound_to_its_conversation() -> None:
    from fastapi import HTTPException

    from sg_api.sessions.tool_tokens import check_conversation

    settings = _settings()
    token, _ = mint_tool_token(
        user_id="u", session_id="s", character="drona", conversation_id="conv_1", settings=settings
    )
    claims = verify_tool_token(token, settings)
    check_conversation(claims, "conv_1")
    with pytest.raises(HTTPException) as other:
        check_conversation(claims, "conv_2")
    assert other.value.status_code == 403
