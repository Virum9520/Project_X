"""C17: behavioural question bank, competency rotation and the opt-in delivery route."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from drona_fixtures import SETTINGS, TOKEN_HEADER, FakeStore, token
from httpx import ASGITransport, AsyncClient

from sg_api.drona.questions import ConceptRubric, select_question
from sg_api.drona.store import get_session_store
from sg_api.main import create_app
from sg_api.vidura.behavioral import BANK, PROBES, ROTATION, next_competency
from sg_api.vidura.delivery import DeliveryStore, DeliverySummary, describe, get_delivery_store
from sg_core.settings import get_settings

DEV = {"X-Dev-User-Id": "user_clerk_1", "X-Dev-User-Name": "Alex"}


def _rubric(key: str) -> ConceptRubric:
    return ConceptRubric(key, key.split(".")[1].replace("_", " ").title(), "", {})


def test_every_rotation_competency_has_star_prompts() -> None:
    for key in ROTATION:
        assert len(BANK[key]) >= 2
        assert all(p.startswith(("Tell", "Describe", "Walk", "Pick", "Why")) for p in BANK[key])


def test_behavioral_question_uses_bank_and_probes_not_answers() -> None:
    q = select_question(_rubric("behavioral.conflict_resolution"), "behavioral")
    assert q.prompt == BANK["behavioral.conflict_resolution"][0]
    assert q.question_id == "behavioral:behavioral.conflict_resolution:0"
    assert set(q.hints) <= set(PROBES.values())
    # Probes ask for missing behaviours; none passes judgement on the person.
    assert not any(w in " ".join(q.hints).lower() for w in ("honest", "confident", "nervous"))


def test_second_variant_then_repeat() -> None:
    rubric = _rubric("behavioral.ownership")
    first = select_question(rubric, "behavioral")
    second = select_question(rubric, "behavioral", exclude={first.question_id})
    assert second.question_id != first.question_id
    repeat = select_question(rubric, "behavioral", exclude={first.question_id, second.question_id})
    assert repeat.repeat


def test_unknown_behavioural_concept_gets_a_generic_prompt() -> None:
    q = select_question(_rubric("behavioral.novel_thing"), "behavioral")
    assert "Novel Thing".lower() in q.prompt.lower()


def test_rotation_skips_used_and_wraps() -> None:
    assert next_competency(set()) == ROTATION[0]
    assert next_competency({ROTATION[0]}) == ROTATION[1]
    assert next_competency(set(ROTATION)) == ROTATION[0]


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    store = FakeStore(
        concepts={k: _rubric(k) for k in ROTATION},
        focus=None,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_session_store] = lambda: store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _fetch(client: AsyncClient, exclude: str | None = None) -> dict[str, str]:
    body: dict[str, object] = {"conversation_id": "conv_1", "kind": "behavioral"}
    if exclude:
        body["exclude_question_ids"] = exclude
    r = await client.post(
        "/v1/agent-tools/fetch_question", json=body, headers={TOKEN_HEADER: token()}
    )
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_vidura_without_focus_rotates_competencies(client: AsyncClient) -> None:
    first = await _fetch(client)
    assert first["concept_id"] == ROTATION[0]
    second = await _fetch(client, exclude=first["question_id"])
    assert second["concept_id"] == ROTATION[1]
    third = await _fetch(client, exclude=f"{first['question_id']},{second['question_id']}")
    assert third["concept_id"] == ROTATION[2]


# --- delivery ---------------------------------------------------------------------------------


@dataclass
class FakeDelivery:
    saved: list[tuple[str, str, DeliverySummary]] = field(default_factory=list)

    async def save(self, clerk_user_id: str, session_id: str, summary: DeliverySummary) -> bool:
        if session_id == "missing":
            return False
        self.saved.append((clerk_user_id, session_id, summary))
        return True


@pytest.fixture
async def delivery_client() -> AsyncIterator[tuple[AsyncClient, FakeDelivery]]:
    fake = FakeDelivery()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    store: DeliveryStore = fake
    app.dependency_overrides[get_delivery_store] = lambda: store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, fake


GOOD = {
    "consent": True,
    "duration_s": 540,
    "samples": 1080,
    "framing_ratio": 0.82,
    "gaze_ratio": 0.64,
    "pace_wpm": 138,
}


async def test_delivery_stores_aggregates(
    delivery_client: tuple[AsyncClient, FakeDelivery],
) -> None:
    client, fake = delivery_client
    r = await client.post("/v1/sessions/abc/delivery", json=GOOD, headers=DEV)
    assert r.status_code == 204
    assert fake.saved[0][0] == "user_clerk_1"


async def test_delivery_requires_opt_in(delivery_client: tuple[AsyncClient, FakeDelivery]) -> None:
    client, fake = delivery_client
    for bad in ({**GOOD, "consent": False}, {k: v for k, v in GOOD.items() if k != "consent"}):
        r = await client.post("/v1/sessions/abc/delivery", json=bad, headers=DEV)
        assert r.status_code == 422
    assert fake.saved == []


async def test_delivery_rejects_anything_but_aggregates(
    delivery_client: tuple[AsyncClient, FakeDelivery],
) -> None:
    client, fake = delivery_client
    for extra in ({"frame": "data:image/png;base64,AAAA"}, {"honesty_score": 0.2}):
        r = await client.post("/v1/sessions/abc/delivery", json={**GOOD, **extra}, headers=DEV)
        assert r.status_code == 422
    r = await client.post(
        "/v1/sessions/abc/delivery", json={**GOOD, "gaze_ratio": 1.5}, headers=DEV
    )
    assert r.status_code == 422
    assert fake.saved == []


async def test_delivery_unknown_session_is_404(
    delivery_client: tuple[AsyncClient, FakeDelivery],
) -> None:
    client, _ = delivery_client
    r = await client.post("/v1/sessions/missing/delivery", json=GOOD, headers=DEV)
    assert r.status_code == 404


async def test_delivery_needs_a_signed_in_learner(
    delivery_client: tuple[AsyncClient, FakeDelivery],
) -> None:
    client, _ = delivery_client
    r = await client.post("/v1/sessions/abc/delivery", json=GOOD)
    assert r.status_code == 401


def test_delivery_memory_text_is_observational() -> None:
    text = describe(DeliverySummary(**GOOD))
    assert "82%" in text and "138 words per minute" in text
    assert "honesty or competence" in text
