"""Bhima routes: agent tools (`log_commitment`, `report_commitment_progress`) and the learner API
(schedules, push, incoming call, accept). In-memory store and budget, mocked ElevenLabs."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from sg_api.accountability.deps import (
    UserRef,
    get_accountability_store,
    get_dispatcher,
    get_policy,
    get_retention_source,
    get_user_directory,
)
from sg_api.main import create_app
from sg_api.sessions.briefing import StubBriefingProvider, get_briefing_provider
from sg_api.sessions.router import get_elevenlabs
from sg_api.sessions.tool_tokens import HEADER, mint_tool_token
from sg_core.accountability import (
    CallDispatcher,
    DispatchPolicy,
    DueConcept,
    InMemoryAccountabilityStore,
    InMemoryBudgetGuard,
    InMemoryRetentionSource,
    PhoneCallChannel,
    WebCallChannel,
)
from sg_core.models.enums import CallChannelKind, CallState, CommitmentStatus
from sg_core.providers.elevenlabs import ElevenLabsClient
from sg_core.settings import Environment, Settings, get_settings

CLERK_ID = "user_clerk_1"
USER = UserRef(uuid.uuid4(), "America/New_York", "Asha")
POLICY = DispatchPolicy(consent_version="v1")
SETTINGS = Settings(  # type: ignore[call-arg]
    _env_file=None,
    environment=Environment.TEST,
    agent_tool_token_secret=SecretStr("x" * 48),
    elevenlabs_agent_ids={"bhima": "agent_bhima"},
)
DEV = {"X-Dev-User-Id": CLERK_ID, "X-Dev-User-Name": "Asha"}


class Directory:
    def __init__(self, known: dict[str, UserRef]) -> None:
        self.known = known

    async def resolve(self, clerk_user_id: str) -> UserRef | None:
        return self.known.get(clerk_user_id)


class Env:
    def __init__(self) -> None:
        self.store = InMemoryAccountabilityStore()
        self.budget = InMemoryBudgetGuard()
        self.retention = InMemoryRetentionSource([DueConcept("dsa.graphs", "Graphs", "due")])
        self.web = WebCallChannel(self.store, None, ring_timeout_seconds=45)
        self.dispatcher = CallDispatcher(
            self.store,
            self.budget,
            {CallChannelKind.WEB: self.web, CallChannelKind.PHONE: PhoneCallChannel()},
            POLICY,
        )


def _token(conversation_id: str | None = "conv_1") -> str:
    token, _ = mint_tool_token(
        user_id=CLERK_ID,
        session_id="ses_1",
        character="bhima",
        conversation_id=conversation_id,
        settings=SETTINGS,
    )
    return token


@pytest.fixture
async def env() -> AsyncIterator[tuple[AsyncClient, Env]]:
    e = Env()
    app = create_app()

    def token_ok(request: httpx.Request) -> httpx.Response:
        assert request.url.params["agent_id"] == "agent_bhima"
        return httpx.Response(200, json={"token": "lk_token", "conversation_id": "conv_bhima"})

    async def fake_elevenlabs() -> AsyncIterator[ElevenLabsClient]:
        async with ElevenLabsClient(
            SecretStr("xi-test"), transport=httpx.MockTransport(token_ok)
        ) as client:
            yield client

    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_accountability_store] = lambda: e.store
    app.dependency_overrides[get_user_directory] = lambda: Directory({CLERK_ID: USER})
    app.dependency_overrides[get_dispatcher] = lambda: e.dispatcher
    app.dependency_overrides[get_policy] = lambda: POLICY
    app.dependency_overrides[get_retention_source] = lambda: e.retention
    app.dependency_overrides[get_elevenlabs] = fake_elevenlabs
    app.dependency_overrides[get_briefing_provider] = StubBriefingProvider
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, e


def _due_local(days: int = 1) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


# ── agent tools ──
async def test_log_commitment_tool_saves_for_the_token_learner(
    env: tuple[AsyncClient, Env],
) -> None:
    http, e = env
    response = await http.post(
        "/v1/agent-tools/log_commitment",
        json={
            "conversation_id": "conv_1",
            "description": "Solve two graph problems",
            "due_local": _due_local(),
            "confirmed_by_learner": True,
        },
        headers={HEADER: _token()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "saved"
    (row,) = e.store.commitments.values()
    assert str(row.id) == body["commitment_id"] and row.user_id == USER.id
    assert row.status is CommitmentStatus.OPEN and row.completion_source is None


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"confirmed_by_learner": False}, 422),
        ({"due_local": "soonish"}, 422),
        ({"due_local": "2020-01-01T09:00"}, 422),
        ({"concept_id": "Not A Concept"}, 422),
    ],
)
async def test_log_commitment_tool_rejects_bad_input(
    env: tuple[AsyncClient, Env], override: dict[str, object], code: int
) -> None:
    http, e = env
    body: dict[str, object] = {
        "conversation_id": "conv_1",
        "description": "Solve two graph problems",
        "due_local": _due_local(),
        "confirmed_by_learner": True,
    } | override
    response = await http.post(
        "/v1/agent-tools/log_commitment", json=body, headers={HEADER: _token()}
    )
    assert response.status_code == code
    assert not e.store.commitments


async def test_tools_require_token_and_matching_conversation(env: tuple[AsyncClient, Env]) -> None:
    http, e = env
    body = {
        "conversation_id": "conv_1",
        "description": "Solve two graph problems",
        "due_local": _due_local(),
        "confirmed_by_learner": True,
    }
    assert (await http.post("/v1/agent-tools/log_commitment", json=body)).status_code == 401
    other = await http.post(
        "/v1/agent-tools/log_commitment", json=body, headers={HEADER: _token("conv_other")}
    )
    assert other.status_code == 403
    assert not e.store.commitments


async def test_report_progress_is_a_self_report(env: tuple[AsyncClient, Env]) -> None:
    http, e = env
    row = await e.store.add_commitment(
        user_id=USER.id, description="Read chapter 4", due_at=None, concept_key=None
    )
    response = await http.post(
        "/v1/agent-tools/report_commitment_progress",
        json={
            "conversation_id": "conv_1",
            "commitment_id": str(row.id),
            "status": "done",
            "learner_words": "finished it this morning",
        },
        headers={HEADER: _token()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["recorded"] == "self_reported"
    assert row.completion_source is not None and row.completion_source.value == "self_reported"
    assert row.reported_note == "finished it this morning"


async def test_report_progress_cannot_reach_other_learners_commitments(
    env: tuple[AsyncClient, Env],
) -> None:
    http, e = env
    theirs = await e.store.add_commitment(
        user_id=uuid.uuid4(), description="Not yours", due_at=None, concept_key=None
    )
    for commitment_id in (str(theirs.id), str(uuid.uuid4())):
        response = await http.post(
            "/v1/agent-tools/report_commitment_progress",
            json={"conversation_id": "conv_1", "commitment_id": commitment_id, "status": "done"},
            headers={HEADER: _token()},
        )
        assert response.status_code == 404
    bad = await http.post(
        "/v1/agent-tools/report_commitment_progress",
        json={"conversation_id": "conv_1", "commitment_id": "nope", "status": "done"},
        headers={HEADER: _token()},
    )
    assert bad.status_code == 422
    assert theirs.reported_status is None


# ── learner API ──
SCHEDULE = {
    "tz": "America/New_York",
    "local_time": "18:00",
    "days": [1, 2, 3, 4, 5],
    "max_duration_seconds": 120,
    "consent_version": "v1",
}


async def test_schedule_crud_requires_consent_and_is_scoped(env: tuple[AsyncClient, Env]) -> None:
    http, _ = env
    assert (await http.post("/v1/accountability/schedules", json=SCHEDULE)).status_code == 401
    refused = await http.post(
        "/v1/accountability/schedules", json=SCHEDULE | {"consent_version": "old"}, headers=DEV
    )
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "consent_required"
    created = await http.post("/v1/accountability/schedules", json=SCHEDULE, headers=DEV)
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]
    assert created.json()["channel"] == "web" and created.json()["local_time"] == "18:00"
    assert len((await http.get("/v1/accountability/schedules", headers=DEV)).json()) == 1
    changed = await http.put(
        f"/v1/accountability/schedules/{schedule_id}",
        json=SCHEDULE | {"local_time": "08:30", "enabled": False},
        headers=DEV,
    )
    assert changed.json()["local_time"] == "08:30" and changed.json()["enabled"] is False
    quiet = await http.put(
        f"/v1/accountability/schedules/{schedule_id}",
        json=SCHEDULE | {"local_time": "23:30"},
        headers=DEV,
    )
    assert quiet.status_code == 422 and quiet.json()["detail"]["code"] == "quiet_hours"
    gone = await http.delete(f"/v1/accountability/schedules/{schedule_id}", headers=DEV)
    assert gone.status_code == 204
    missing = await http.delete(f"/v1/accountability/schedules/{schedule_id}", headers=DEV)
    assert missing.status_code == 404


async def test_push_subscription_roundtrip(env: tuple[AsyncClient, Env]) -> None:
    http, e = env
    body = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
    assert (
        await http.post("/v1/accountability/push-subscriptions", json=body, headers=DEV)
    ).status_code == 204
    assert len(await e.store.list_push_subscriptions(USER.id)) == 1
    insecure = {"endpoint": "http://insecure/abc", "keys": {"p256dh": "k", "auth": "a"}}
    assert (
        await http.post("/v1/accountability/push-subscriptions", json=insecure, headers=DEV)
    ).status_code == 422
    await http.post(
        "/v1/accountability/push-subscriptions/revoke",
        json={"endpoint": body["endpoint"]},
        headers=DEV,
    )
    assert await e.store.list_push_subscriptions(USER.id) == []


async def ring(e: Env) -> uuid.UUID:
    now = datetime.now(UTC)
    await e.store.ensure_test_occurrence(
        request_id=f"req-{uuid.uuid4()}", user_id=USER.id, scheduled_for=now
    )
    report = await e.dispatcher.run_once(now)
    assert report["ringing"] == 1
    attempt = await e.store.ringing_attempt_for_user(USER.id)
    assert attempt is not None
    return attempt.id


async def test_incoming_call_poll_and_accept_starts_bhima_with_retention(
    env: tuple[AsyncClient, Env],
) -> None:
    http, e = env
    assert (await http.get("/v1/accountability/calls/incoming", headers=DEV)).json() == {
        "call": None
    }
    attempt_id = await ring(e)
    incoming = (await http.get("/v1/accountability/calls/incoming", headers=DEV)).json()["call"]
    assert incoming["attempt_id"] == str(attempt_id) and incoming["caller"] == "Bhima"

    accepted = await http.post(f"/v1/accountability/calls/{attempt_id}/accept", headers=DEV)
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["session"]["conversation_token"] == "lk_token"
    assert body["session"]["character"] == "bhima"
    variables = body["session"]["dynamic_variables"]
    assert variables["retention_concept"] == "dsa.graphs"
    assert variables["retention_concept_title"] == "Graphs"
    assert body["max_duration_seconds"] == 120 and body["retention_concept"] == "dsa.graphs"
    assert body["wrap_up_after_seconds"] < body["hard_stop_after_seconds"] == 120
    attempt = e.store.attempts[attempt_id]
    assert attempt.state is CallState.CONNECTED and attempt.el_conversation_id == "conv_bhima"
    assert [a[1] for a in e.retention.asked] == ["dsa.graphs"]

    assert (await http.get("/v1/accountability/calls/incoming", headers=DEV)).json() == {
        "call": None
    }
    second = await http.post(f"/v1/accountability/calls/{attempt_id}/accept", headers=DEV)
    assert second.status_code == 409

    ended = await http.post(
        f"/v1/accountability/calls/{attempt_id}/end", json={"duration_seconds": 75}, headers=DEV
    )
    assert ended.status_code == 204
    assert e.store.attempts[attempt_id].state is CallState.COMPLETED
    assert e.budget.settled  # settled at the real duration, not the hold


async def test_accept_without_retention_candidates_sends_none(env: tuple[AsyncClient, Env]) -> None:
    http, e = env
    e.retention.due = []
    attempt_id = await ring(e)
    body = (await http.post(f"/v1/accountability/calls/{attempt_id}/accept", headers=DEV)).json()
    assert body["retention_concept"] is None
    assert body["session"]["dynamic_variables"]["retention_concept"] == "none"


async def test_accept_expired_or_foreign_call_is_refused(env: tuple[AsyncClient, Env]) -> None:
    http, e = env
    attempt_id = await ring(e)
    e.store.attempts[attempt_id].dispatched_at = datetime.now(UTC) - timedelta(minutes=5)
    late = await http.post(f"/v1/accountability/calls/{attempt_id}/accept", headers=DEV)
    assert late.status_code == 410
    foreign = await http.post(f"/v1/accountability/calls/{uuid.uuid4()}/accept", headers=DEV)
    assert foreign.status_code == 404


async def test_failed_session_start_fails_the_call(env: tuple[AsyncClient, Env]) -> None:
    http, e = env
    app = http._transport.app  # type: ignore[attr-defined]

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "down"})

    async def broken() -> AsyncIterator[ElevenLabsClient]:
        async with ElevenLabsClient(
            SecretStr("xi-test"), transport=httpx.MockTransport(boom)
        ) as client:
            yield client

    app.dependency_overrides[get_elevenlabs] = broken
    attempt_id = await ring(e)
    response = await http.post(f"/v1/accountability/calls/{attempt_id}/accept", headers=DEV)
    assert response.status_code == 502
    assert e.store.attempts[attempt_id].state is CallState.FAILED
    assert not e.budget.holds


async def test_decline_marks_the_call_cancelled(env: tuple[AsyncClient, Env]) -> None:
    http, e = env
    attempt_id = await ring(e)
    response = await http.post(f"/v1/accountability/calls/{attempt_id}/decline", headers=DEV)
    assert response.status_code == 204
    assert e.store.attempts[attempt_id].state is CallState.CANCELLED


async def test_learner_commitments_list_shows_source(env: tuple[AsyncClient, Env]) -> None:
    http, e = env
    await e.store.add_commitment(
        user_id=USER.id, description="Read chapter 4", due_at=None, concept_key=None
    )
    rows = (await http.get("/v1/accountability/commitments", headers=DEV)).json()
    assert rows[0]["description"] == "Read chapter 4"
    assert rows[0]["status"] == "open" and rows[0]["completion_source"] is None
