"""`/v1/agent-tools/record_observation`: auth, validation, provisional glow and neutrality."""

import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "tests"))

from evidence_fixtures import BS, ScriptedLLM, World

from sg_api.agent_tools.record_observation import (
    ObservationDeps,
    get_observation_deps,
)
from sg_api.main import create_app
from sg_api.sessions.tool_tokens import HEADER, mint_tool_token
from sg_core.evidence import MicroJudge
from sg_core.models.enums import MemoryStatus
from sg_core.settings import Environment, Settings, get_settings

SETTINGS = Settings(  # type: ignore[call-arg]
    _env_file=None, environment=Environment.TEST, agent_tool_token_secret=SecretStr("x" * 48)
)
GOOD = {"outcome": "demonstrated", "uncertainty": 0.1, "rationale": "good"}


def body(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "conversation_id": "conv_1",
        "concept_id": BS,
        "question_id": "q1",
        "dimension": "explanation",
        "outcome": "correct",
        "assistance": "independent",
        "evidence_quote": "it halves the search range each step",
    }
    return {**base, **kw}


def token(character: str = "drona", conversation_id: str | None = "conv_1") -> str:
    t, _ = mint_tool_token(
        user_id="clerk_1",
        session_id="ses_abc",
        character=character,
        conversation_id=conversation_id,
        settings=SETTINGS,
    )
    return t


@pytest.fixture
async def env() -> AsyncIterator[tuple[AsyncClient, World, ScriptedLLM]]:
    world = World()
    llm = ScriptedLLM(GOOD)

    async def deps() -> AsyncIterator[ObservationDeps]:
        yield ObservationDeps(world.store, MicroJudge(llm, "tiny"))

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_observation_deps] = deps
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, world, llm


async def post(c: AsyncClient, payload: dict[str, Any], tok: str | None = None) -> Any:
    return await c.post(
        "/v1/agent-tools/record_observation",
        json=payload,
        headers={HEADER: tok if tok is not None else token()},
    )


async def test_requires_a_valid_tool_token(env: tuple[AsyncClient, World, ScriptedLLM]) -> None:
    c, world, _ = env
    r = await c.post("/v1/agent-tools/record_observation", json=body())
    assert r.status_code == 401
    r = await post(c, body(), "garbage")
    assert r.status_code == 401
    assert not world.store.evidence


async def test_conversation_must_match_the_token(
    env: tuple[AsyncClient, World, ScriptedLLM],
) -> None:
    c, world, _ = env
    r = await post(c, body(conversation_id="conv_other"))
    assert r.status_code == 403 and not world.store.evidence


async def test_unknown_learner_is_404(env: tuple[AsyncClient, World, ScriptedLLM]) -> None:
    c, world, _ = env
    world.store.users.clear()
    assert (await post(c, body())).status_code == 404


async def test_positive_answer_creates_provisional_glow_and_a_neutral_reply(
    env: tuple[AsyncClient, World, ScriptedLLM],
) -> None:
    c, world, llm = env
    r = await post(c, body())
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "recorded"
    # The agent is never told the grade: no outcome, score or growth in the reply.
    assert set(data) == {"status", "message"}
    assert "demonstrated" not in r.text and "glow" not in r.text.lower()

    [session] = world.store.sessions.values()
    assert session.user_id == world.user_id and session.conversation_id == "conv_1"
    assert session.attributes["public_session_id"] == "ses_abc" and session.character == "drona"
    [memory] = world.store.memories.values()
    assert memory.status is MemoryStatus.PROVISIONAL and memory.new.evidence_ids
    # Provisional only: the garden is untouched.
    assert not world.store.revisions and not world.store.plants
    assert llm.calls[0]["model"] == "tiny"
    assert [e[1] for e in world.store.events] == ["garden.provisional_growth"]


async def test_the_token_identity_wins_over_anything_in_the_body(
    env: tuple[AsyncClient, World, ScriptedLLM],
) -> None:
    c, world, _ = env
    r = await post(c, {**body(), "user_id": str(uuid.uuid4()), "character": "bhima"})
    assert r.status_code == 200
    assert next(iter(world.store.sessions.values())).user_id == world.user_id


async def test_two_calls_in_one_conversation_share_a_session(
    env: tuple[AsyncClient, World, ScriptedLLM],
) -> None:
    c, world, _ = env
    await post(c, body())
    await post(c, body(dimension="application", evidence_quote="I would use two pointers here"))
    assert len(world.store.sessions) == 1


@pytest.mark.parametrize("character", ["bhima", "krishna", "sanjaya"])
async def test_non_assessing_characters_are_refused(
    env: tuple[AsyncClient, World, ScriptedLLM], character: str
) -> None:
    c, world, _ = env
    r = await post(c, body(), token(character))
    assert r.status_code == 403 and not world.store.sessions


async def test_panel_sessions_are_vidura_panel_interviews(
    env: tuple[AsyncClient, World, ScriptedLLM],
) -> None:
    c, world, _ = env
    assert (await post(c, body(), token("panel"))).status_code == 200
    [session] = world.store.sessions.values()
    assert (session.character, session.mode) == ("vidura", "panel_interview")


@pytest.mark.parametrize(
    ("override", "status"),
    [
        ({"dimension": "vibes"}, 422),
        ({"outcome": "great"}, 422),
        ({"assistance": "none"}, 422),
        ({"concept_id": "Not A Key"}, 422),
        ({"evidence_quote": ""}, 422),
        ({"concept_id": "dsa.does_not_exist"}, 422),
    ],
)
async def test_bad_requests_are_rejected(
    env: tuple[AsyncClient, World, ScriptedLLM], override: dict[str, Any], status: int
) -> None:
    c, world, _ = env
    r = await post(c, body(**override))
    assert r.status_code == status and not world.store.evidence


async def test_unknown_concept_reports_a_stable_code(
    env: tuple[AsyncClient, World, ScriptedLLM],
) -> None:
    c, _, _ = env
    r = await post(c, body(concept_id="dsa.does_not_exist"))
    assert r.json()["detail"]["code"] == "unknown_concept"


async def test_a_bad_micro_judge_never_breaks_the_call(
    env: tuple[AsyncClient, World, ScriptedLLM],
) -> None:
    c, world, llm = env
    llm.bodies = [RuntimeError("openrouter down")]
    r = await post(c, body())
    assert r.status_code == 200
    assert world.store.evidence and not world.store.memories  # recorded, no glow
