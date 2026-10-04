from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from sg_api.main import create_app
from sg_api.sessions.briefing import SessionBriefing, get_briefing_provider
from sg_api.sessions.identity import Learner
from sg_api.sessions.tool_tokens import HEADER, mint_tool_token
from sg_core.settings import Environment, Settings, get_settings

SETTINGS = Settings(  # type: ignore[call-arg]
    _env_file=None, environment=Environment.TEST, agent_tool_token_secret=SecretStr("x" * 48)
)


class Recording:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    async def build(
        self,
        learner: Learner,
        character: str,
        focus_concept_id: str | None,
        query_hint: str | None = None,
    ) -> SessionBriefing:
        self.calls.append((learner.user_id, character, focus_concept_id, query_hint))
        return SessionBriefing(text="BRIEF", focus_concept="none", due_concepts=["Hash tables"])


@pytest.fixture
async def client() -> AsyncIterator[tuple[AsyncClient, Recording]]:
    app = create_app()
    recording = Recording()
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_briefing_provider] = lambda: recording
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, recording


def _token(conversation_id: str | None = "conv_1") -> str:
    token, _ = mint_tool_token(
        user_id="user_clerk_1",
        session_id="ses_1",
        character="drona",
        conversation_id=conversation_id,
        settings=SETTINGS,
    )
    return token


async def test_get_briefing_uses_token_identity(client: tuple[AsyncClient, Recording]) -> None:
    http, recording = client
    response = await http.post(
        "/v1/agent-tools/get_briefing",
        json={"conversation_id": "conv_1", "reason": "learner mentioned earlier work"},
        headers={HEADER: _token()},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "briefing": "BRIEF",
        "focus_concept": "none",
        "due_concepts": ["Hash tables"],
    }
    assert recording.calls == [("user_clerk_1", "drona", None, "learner mentioned earlier work")]


async def test_get_briefing_requires_token(client: tuple[AsyncClient, Recording]) -> None:
    http, _ = client
    response = await http.post("/v1/agent-tools/get_briefing", json={"conversation_id": "conv_1"})
    assert response.status_code == 401


async def test_get_briefing_rejects_other_conversation(
    client: tuple[AsyncClient, Recording],
) -> None:
    http, recording = client
    response = await http.post(
        "/v1/agent-tools/get_briefing",
        json={"conversation_id": "conv_other"},
        headers={HEADER: _token()},
    )
    assert response.status_code == 403
    assert recording.calls == []
