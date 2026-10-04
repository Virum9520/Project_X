from collections.abc import AsyncIterator

import pytest
from drona_fixtures import TOKEN_HEADER, FakeStore, make_client, token
from httpx import AsyncClient


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async for c in make_client():
        yield c


def _body(**extra: object) -> dict[str, object]:
    return {"conversation_id": "conv_1", "kind": "concept_check", **extra}


async def test_requires_a_token(client: AsyncClient) -> None:
    assert (await client.post("/v1/agent-tools/fetch_question", json=_body())).status_code == 401


async def test_uses_the_session_focus_when_no_concept_is_given(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/agent-tools/fetch_question", json=_body(), headers={TOKEN_HEADER: token()}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["concept_id"] == "dsa.binary_search"
    assert body["question_id"].startswith("concept_check:dsa.binary_search:")
    assert body["prompt"]


async def test_excludes_used_questions(client: AsyncClient) -> None:
    first = (
        await client.post(
            "/v1/agent-tools/fetch_question", json=_body(), headers={TOKEN_HEADER: token()}
        )
    ).json()
    second = (
        await client.post(
            "/v1/agent-tools/fetch_question",
            json=_body(exclude_question_ids=first["question_id"]),
            headers={TOKEN_HEADER: token()},
        )
    ).json()
    assert second["question_id"] != first["question_id"]


async def test_wrong_conversation_is_forbidden(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/agent-tools/fetch_question",
        json=_body(conversation_id="conv_other"),
        headers={TOKEN_HEADER: token()},
    )
    assert r.status_code == 403


async def test_coding_problems_are_not_served_here(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/agent-tools/fetch_question",
        json=_body(kind="coding_problem"),
        headers={TOKEN_HEADER: token()},
    )
    assert r.status_code == 422


async def test_unknown_concept_is_a_correctable_error(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/agent-tools/fetch_question",
        json=_body(concept_id="dsa.nope"),
        headers={TOKEN_HEADER: token()},
    )
    assert r.status_code == 404


async def test_teach_back_note_keeps_the_agent_a_student() -> None:
    async for client in make_client():
        r = await client.post(
            "/v1/agent-tools/fetch_question",
            json=_body(kind="teach_back"),
            headers={TOKEN_HEADER: token()},
        )
        assert "confused student" in r.json()["note"]


async def test_no_focus_and_no_concept_is_422() -> None:
    async for client in make_client(store=FakeStore(focus=None)):
        r = await client.post(
            "/v1/agent-tools/fetch_question", json=_body(), headers={TOKEN_HEADER: token()}
        )
        assert r.status_code == 422


async def test_database_failure_is_503() -> None:
    async for client in make_client(store=FakeStore(broken=True)):
        r = await client.post(
            "/v1/agent-tools/fetch_question", json=_body(), headers={TOKEN_HEADER: token()}
        )
        assert r.status_code == 503
