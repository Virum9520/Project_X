"""Owner-console API: capability checks, audit and Call now, against an in-memory store."""

import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from test_auth import ISSUER, KID, OWNER, USERS, MemoryAuditSink, auth, clerk_api

from sg_api.admin.deps import get_admin_store
from sg_api.admin.dispatcher import (
    DispatchCommand,
    DispatchOutcome,
    DispatchRejectedError,
    StubCallDispatcher,
)
from sg_api.admin.schemas import (
    AgentRow,
    AuditPage,
    BudgetStatus,
    CallsReport,
    CostReport,
    Freshness,
    Overview,
    QualityReport,
    UsageTotals,
    UserDetail,
    UserPage,
)
from sg_api.admin.store import CooldownError, TestCallRecord
from sg_api.auth import Identity
from sg_api.main import create_app
from sg_core.economics.budget import BudgetExceededError
from sg_core.identity import (
    Capability,
    ClerkTokenVerifier,
    ClerkUserDirectory,
    StaticGrantStore,
)
from sg_core.models.enums import CallChannelKind, CallState
from sg_core.settings import Environment, Settings, get_settings

assert KID and ISSUER  # re-exported helpers share one signing key with test_auth

USERS["user_analyst"] = ("analyst@example.com", True, True)
USERS["user_dev"] = ("dev@example.com", True, True)
ORIGIN = {"Origin": "http://localhost:3001"}
TEST_NUMBER = "+15555550123"

SETTINGS = Settings(  # type: ignore[call-arg]
    _env_file=None,
    environment=Environment.TEST,
    call_now_approved_targets=["web", TEST_NUMBER],
    call_now_cooldown_seconds=60,
    call_now_max_duration_seconds=300,
    developer_monthly_budget_usd=Decimal("1"),
    elevenlabs_agent_ids={"bhima": "agent_bhima"},
    elevenlabs_api_key=SecretStr("sk-secret"),
)


class FakeStore:
    """Mirrors the SQL store's Call now rules: replay by request ID, cooldown, budget hold."""

    def __init__(self) -> None:
        self.placed: dict[str, TestCallRecord] = {}
        self.created_at: list[datetime] = []
        self.held = Decimal(0)
        self.limit = Decimal(0)
        self.dispatches: list[tuple[CallState, bool]] = []
        self.audit_args: list[dict[str, object]] = []

    async def ping(self) -> None:
        return None

    async def overview(self, now: datetime) -> Overview:
        return Overview(
            generated_at=now,
            period=now.strftime("%Y-%m"),
            active_users_30d=3,
            completed_sessions_30d=9,
            spend_month_to_date_usd=1.5,
            projected_month_end_usd=4.5,
            spend_by_cost_center={"learner": 1.5},
            failed_sessions_7d=0,
            failed_calls_7d=0,
            failed_provider_events=0,
            developer_budget=None,
            freshness=Freshness(
                usage_events_at=None,
                cost_entries_at=None,
                sessions_at=None,
                provider_events_at=None,
            ),
        )

    async def list_users(self, q: str | None, limit: int, offset: int) -> UserPage:
        return UserPage(items=[], total=0, limit=limit, offset=offset)

    async def get_user(self, user_id: uuid.UUID, now: datetime) -> UserDetail | None:
        return None

    async def costs(self, start: date, end: date, group_by: str, now: datetime) -> CostReport:
        return CostReport(
            start=start,
            end=end,
            group_by=group_by,  # type: ignore[arg-type]
            total_usd=0,
            by_kind={},
            reconciled_share=0,
            groups=[],
            daily=[],
            usage=UsageTotals(
                events=0,
                connected_seconds=0,
                input_tokens=0,
                output_tokens=0,
                token_reporting_events=0,
                sandbox_seconds=0,
            ),
        )

    async def calls(self, now: datetime) -> CallsReport:
        return CallsReport(generated_at=now, upcoming=[], active=[], recent=[], state_counts_7d={})

    async def agents(self, agent_ids: dict[str, str], now: datetime) -> list[AgentRow]:
        return [
            AgentRow(
                character="bhima",
                agent_id=agent_ids.get("bhima"),
                configured="bhima" in agent_ids,
                sessions_30d=0,
                failed_30d=0,
                test_sessions_30d=0,
                avg_duration_seconds=None,
                versions=[],
            )
        ]

    async def quality(self, now: datetime) -> QualityReport:
        return QualityReport(
            generated_at=now,
            assessments_by_status={},
            judge_backlog=0,
            oldest_pending_assessment_age_s=None,
            open_disputes=0,
            resolved_disputes=0,
            disputes_upheld=0,
            disagreement_rate=None,
            provider_events_by_status={},
            webhook_oldest_unprocessed_age_s=None,
            webhook_avg_latency_s_24h=None,
            failed_events=[],
            failed_sessions_7d=0,
            interrupted_sessions_7d=0,
        )

    async def audit(
        self,
        *,
        action_prefix: str | None,
        actor_email: str | None,
        before: datetime | None,
        limit: int,
    ) -> AuditPage:
        self.audit_args.append({"action": action_prefix, "actor": actor_email, "limit": limit})
        return AuditPage(items=[], next_before=None)

    async def developer_budget(self, limit_usd: Decimal, now: datetime) -> BudgetStatus:
        return BudgetStatus(
            key="developer:x", limit_usd=float(limit_usd), committed_usd=float(self.held)
        )

    async def create_test_call(
        self,
        *,
        request_id: str,
        channel: CallChannelKind,
        estimate_usd: Decimal,
        budget_limit_usd: Decimal,
        cooldown_s: int,
        now: datetime,
    ) -> tuple[TestCallRecord, bool]:
        if request_id in self.placed:
            return self.placed[request_id], False
        if self.created_at:
            wait = cooldown_s - (now - self.created_at[-1]).total_seconds()
            if wait > 0:
                raise CooldownError(int(wait) + 1)
        if self.held + estimate_usd > budget_limit_usd:
            raise BudgetExceededError("developer", budget_limit_usd, self.held, estimate_usd)
        self.held += estimate_usd
        self.limit = budget_limit_usd
        record = TestCallRecord(
            uuid.uuid4(), uuid.uuid4(), request_id, CallState.QUEUED, channel, None
        )
        self.placed[request_id] = record
        self.created_at.append(now)
        self._estimate = estimate_usd
        return record, True

    async def record_dispatch(
        self,
        record: TestCallRecord,
        *,
        state: CallState,
        el_conversation_id: str | None,
        twilio_call_sid: str | None,
        error: str | None,
        release_budget: bool,
    ) -> None:
        self.dispatches.append((state, release_budget))
        if release_budget:
            self.held -= self._estimate


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def dispatcher() -> StubCallDispatcher:
    return StubCallDispatcher()


@pytest.fixture
def audit() -> MemoryAuditSink:
    return MemoryAuditSink()


@pytest.fixture
def app(store: FakeStore, dispatcher: StubCallDispatcher, audit: MemoryAuditSink) -> FastAPI:
    app = create_app()
    http = httpx.AsyncClient(transport=httpx.MockTransport(clerk_api))
    app.state.identity = Identity(
        verifier=ClerkTokenVerifier(
            ISSUER, authorized_parties=["http://localhost:3001"], http=http
        ),
        directory=ClerkUserDirectory("https://api.clerk.com", "sk_test", http=http),
        grants=StaticGrantStore(
            {
                "user_support": frozenset({Capability.CONSOLE_ACCESS, Capability.USERS_READ}),
                "user_analyst": frozenset(
                    {
                        Capability.CONSOLE_ACCESS,
                        Capability.USAGE_READ,
                        Capability.CALLS_READ,
                        Capability.QUALITY_READ,
                    }
                ),
                "user_dev": frozenset(
                    {Capability.CONSOLE_ACCESS, Capability.CALLS_READ, Capability.CALLS_TRIGGER}
                ),
            }
        ),
        audit=audit,
        owner_emails=frozenset({OWNER}),
        admin_origins=frozenset({"http://localhost:3001"}),
    )
    app.state.call_dispatcher = dispatcher
    app.dependency_overrides[get_admin_store] = lambda: store
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


READ_ROUTES: list[tuple[str, Capability]] = [
    ("/v1/admin/overview", Capability.USAGE_READ),
    ("/v1/admin/users", Capability.USERS_READ),
    (f"/v1/admin/users/{uuid.uuid4()}", Capability.USERS_READ),
    ("/v1/admin/costs", Capability.USAGE_READ),
    ("/v1/admin/calls", Capability.CALLS_READ),
    ("/v1/admin/agents", Capability.CALLS_READ),
    ("/v1/admin/calls/now/options", Capability.CALLS_READ),
    ("/v1/admin/quality", Capability.QUALITY_READ),
    ("/v1/admin/system", Capability.QUALITY_READ),
    ("/v1/admin/audit", Capability.AUDIT_READ),
]
GRANTED = {
    "user_support": {Capability.CONSOLE_ACCESS, Capability.USERS_READ},
    "user_analyst": {
        Capability.CONSOLE_ACCESS,
        Capability.USAGE_READ,
        Capability.CALLS_READ,
        Capability.QUALITY_READ,
    },
}


@pytest.mark.parametrize(("path", "capability"), READ_ROUTES)
async def test_read_routes_need_authentication(
    client: AsyncClient, path: str, capability: Capability
) -> None:
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=auth("user_learner"))).status_code == 403


@pytest.mark.parametrize(("path", "capability"), READ_ROUTES)
@pytest.mark.parametrize("user", ["user_support", "user_analyst"])
async def test_read_routes_enforce_their_capability(
    client: AsyncClient, path: str, capability: Capability, user: str
) -> None:
    response = await client.get(path, headers=auth(user))
    if capability in GRANTED[user]:
        # 404 is the (empty) fake store answering for an unknown user, not a refusal.
        assert response.status_code in (200, 404), response.text
    else:
        assert response.status_code == 403
        assert response.json()["detail"] == f"missing capability {capability.value}"


@pytest.mark.parametrize(("path", "capability"), READ_ROUTES)
async def test_owner_reaches_every_read_route(
    client: AsyncClient, path: str, capability: Capability
) -> None:
    response = await client.get(path, headers=auth("user_owner"))
    assert response.status_code in (200, 404), response.text


async def test_mfa_is_required_for_console_data(client: AsyncClient) -> None:
    response = await client.get("/v1/admin/overview", headers=auth("user_owner", fva=[1, -1]))
    assert response.status_code == 403


async def test_costs_rejects_bad_ranges(client: AsyncClient) -> None:
    owner = auth("user_owner")
    backwards = await client.get("/v1/admin/costs?start=2026-10-05&end=2026-10-01", headers=owner)
    assert backwards.status_code == 422
    too_long = await client.get("/v1/admin/costs?start=2024-01-01&end=2026-10-01", headers=owner)
    assert too_long.status_code == 422
    bad_group = await client.get("/v1/admin/costs?group_by=password", headers=owner)
    assert bad_group.status_code == 422


async def test_user_search_is_bounded(client: AsyncClient) -> None:
    owner = auth("user_owner")
    assert (await client.get("/v1/admin/users?limit=1000", headers=owner)).status_code == 422
    assert (await client.get("/v1/admin/users?q=" + "x" * 101, headers=owner)).status_code == 422


async def test_system_status_never_returns_secrets(client: AsyncClient) -> None:
    response = await client.get("/v1/admin/system", headers=auth("user_owner"))
    body = response.json()
    assert "sk-secret" not in response.text
    assert body["configured"]["elevenlabs_api_key"] is True
    assert body["configured"]["openai"] is False
    stub = next(c for c in body["components"] if c["name"] == "call_dispatcher")
    assert stub["ok"] is False  # the stub places no calls


# ── Call now ──
def call_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "request_id": f"req-{uuid.uuid4().hex[:12]}",
        "agent": "bhima",
        "target": "web",
        "test_profile": "fresh_learner",
        "duration_seconds": 60,
    }
    return {**body, **overrides}


def headers(user: str = "user_owner") -> dict[str, str]:
    return {**auth(user), **ORIGIN}


async def test_call_now_requires_the_trigger_capability(
    client: AsyncClient, audit: MemoryAuditSink, dispatcher: StubCallDispatcher
) -> None:
    for user in ("user_support", "user_analyst"):
        response = await client.post("/v1/admin/calls/now", json=call_body(), headers=headers(user))
        assert response.status_code == 403
        assert response.json()["detail"] == "missing capability calls.trigger"
    assert dispatcher.sent == []
    # refused attempts are still audited
    assert [e.status_code for e in audit.events] == [403, 403]


async def test_call_now_is_blocked_cross_site(
    client: AsyncClient, dispatcher: StubCallDispatcher
) -> None:
    response = await client.post(
        "/v1/admin/calls/now",
        json=call_body(),
        headers={**auth("user_owner"), "Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert dispatcher.sent == []


async def test_call_now_dispatches_once_and_audits(
    client: AsyncClient,
    audit: MemoryAuditSink,
    dispatcher: StubCallDispatcher,
    store: FakeStore,
) -> None:
    body = call_body(target=TEST_NUMBER, duration_seconds=120, agent_version="v7")
    response = await client.post("/v1/admin/calls/now", json=body, headers=headers("user_dev"))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["replayed"] is False
    assert data["state"] == "queued"
    assert data["channel"] == "phone"
    # 2 minutes at the default US$0.10/min estimate
    assert data["estimated_cost_usd"] == pytest.approx(0.2)

    [command] = dispatcher.sent
    assert isinstance(command, DispatchCommand)
    assert command.is_test is True
    assert command.agent_id == "agent_bhima"
    assert command.agent_version == "v7"
    assert command.max_duration_seconds == 120
    assert command.requested_by == "user_dev"
    assert command.request_id == body["request_id"]

    [event] = audit.events
    assert event.action == "calls.now"
    assert event.target == f"call:{data['occurrence_id']}"
    assert event.status_code == 200
    assert event.after is not None
    assert event.after["target"] == "********0123"  # the number is masked in the audit record
    assert TEST_NUMBER not in str(event.after)
    assert store.dispatches == [(CallState.QUEUED, False)]


async def test_repeated_clicks_never_dial_twice(
    client: AsyncClient, dispatcher: StubCallDispatcher, audit: MemoryAuditSink
) -> None:
    body = call_body()
    first = await client.post("/v1/admin/calls/now", json=body, headers=headers())
    second = await client.post("/v1/admin/calls/now", json=body, headers=headers())
    assert first.status_code == second.status_code == 200
    assert first.json()["replayed"] is False
    assert second.json()["replayed"] is True
    assert second.json()["occurrence_id"] == first.json()["occurrence_id"]
    assert len(dispatcher.sent) == 1
    assert [e.action for e in audit.events] == ["calls.now", "calls.now.replay"]


async def test_a_new_request_id_waits_out_the_cooldown(
    client: AsyncClient, dispatcher: StubCallDispatcher
) -> None:
    assert (
        await client.post("/v1/admin/calls/now", json=call_body(), headers=headers())
    ).status_code == 200
    again = await client.post("/v1/admin/calls/now", json=call_body(), headers=headers())
    assert again.status_code == 429
    assert int(again.headers["Retry-After"]) > 0
    assert len(dispatcher.sent) == 1


@pytest.mark.parametrize(
    ("override", "status_code"),
    [
        ({"target": "+19995550000"}, 403),  # not on the approved list
        ({"target": "tel:+15555550123"}, 403),
        ({"agent": "nobody"}, 422),
        ({"duration_seconds": 10}, 422),
        ({"duration_seconds": 301}, 422),  # above CALL_NOW_MAX_DURATION_SECONDS
        ({"duration_seconds": 99999}, 422),
        ({"request_id": "short"}, 422),
        ({"request_id": "has spaces in it"}, 422),
        ({"test_profile": "a_real_learner"}, 422),
    ],
)
async def test_call_now_rejects_bad_requests(
    client: AsyncClient,
    dispatcher: StubCallDispatcher,
    override: dict[str, object],
    status_code: int,
) -> None:
    response = await client.post(
        "/v1/admin/calls/now", json=call_body(**override), headers=headers()
    )
    assert response.status_code == status_code, response.text
    assert dispatcher.sent == []


async def test_call_now_stops_at_the_developer_budget(
    client: AsyncClient, dispatcher: StubCallDispatcher, store: FakeStore
) -> None:
    store.held = Decimal("0.95")  # US$1 limit, a 60s call estimates US$0.10
    response = await client.post("/v1/admin/calls/now", json=call_body(), headers=headers())
    assert response.status_code == 402
    assert dispatcher.sent == []


class RejectingDispatcher:
    name = "rejecting"

    async def dispatch(self, command: DispatchCommand) -> DispatchOutcome:
        raise DispatchRejectedError("provider said no")


class TimingOutDispatcher:
    name = "timeout"

    async def dispatch(self, command: DispatchCommand) -> DispatchOutcome:
        raise TimeoutError("read timeout")


async def test_rejected_dispatch_releases_the_hold(
    app: FastAPI, client: AsyncClient, store: FakeStore
) -> None:
    app.state.call_dispatcher = RejectingDispatcher()
    response = await client.post("/v1/admin/calls/now", json=call_body(), headers=headers())
    assert response.status_code == 502
    assert store.dispatches == [(CallState.FAILED, True)]
    assert store.held == 0


async def test_uncertain_dispatch_is_unknown_and_keeps_the_hold(
    app: FastAPI, client: AsyncClient, store: FakeStore
) -> None:
    app.state.call_dispatcher = TimingOutDispatcher()
    response = await client.post("/v1/admin/calls/now", json=call_body(), headers=headers())
    assert response.status_code == 200
    assert response.json()["state"] == "unknown"
    assert store.dispatches == [(CallState.UNKNOWN, False)]
    assert store.held > 0


async def test_options_expose_limits_and_budget(client: AsyncClient) -> None:
    response = await client.get("/v1/admin/calls/now/options", headers=auth("user_owner"))
    data = response.json()
    assert data["targets"] == ["web", TEST_NUMBER]
    assert data["max_duration_seconds"] == 300
    assert data["cooldown_seconds"] == 60
    assert data["dispatcher"] == "stub"
    assert data["cost_per_minute_usd"] == pytest.approx(0.1)
    assert data["developer_budget"]["limit_usd"] == 1.0


async def test_audit_listing_passes_filters(client: AsyncClient, store: FakeStore) -> None:
    response = await client.get(
        "/v1/admin/audit?action=calls&actor=owner&limit=5", headers=auth("user_owner")
    )
    assert response.status_code == 200
    assert store.audit_args == [{"action": "calls", "actor": "owner", "limit": 5}]
