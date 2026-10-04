"""Owner assistant routes: owner-only access, audit of questions and tool calls, errors."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from test_auth import ISSUER, KID, OWNER, USERS, MemoryAuditSink, auth, clerk_api

from sg_api.assistant import router as assistant_router
from sg_api.auth import Identity
from sg_api.main import create_app
from sg_core.economics.budget import Hold
from sg_core.identity import Capability, ClerkTokenVerifier, ClerkUserDirectory, StaticGrantStore
from sg_core.providers.llm import LLMResponse, LLMUsage, ToolCall
from sg_core.settings import Environment, Settings, get_settings
from sg_mcp_gateway import GatewayLimits, McpGateway, OwnerAssistant
from sg_mcp_gateway.mcp_client import McpResult, McpTool

assert KID and ISSUER

USERS["user_ops"] = ("ops@example.com", True, True)
USERS["user_ops_no_mfa"] = ("ops2@example.com", True, False)
ORIGIN = {"Origin": "http://localhost:3001"}
SETTINGS = Settings(_env_file=None, environment=Environment.TEST)  # type: ignore[call-arg]
SQL = "SELECT * FROM analytics.daily_cost"
FINAL = json.dumps(
    {
        "answer": "Total $1.20",
        "basis": {
            "date_range": "Oct 2026",
            "metrics": ["sum(usd_total)"],
            "filters": [],
            "freshness": "now",
            "amounts": "mixed",
        },
        "hypotheses": [],
    }
)


class OkBudget:
    @asynccontextmanager
    async def hold(self, amount_usd: Decimal) -> AsyncIterator[Hold]:
        import uuid

        h = Hold(uuid.uuid4(), amount_usd)
        yield h


class Script:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses

    async def complete(self, messages: Any, **kwargs: Any) -> LLMResponse:
        return self.responses.pop(0)


class Tiger:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def list_tools(self) -> list[McpTool]:
        return [McpTool("db_execute_query", "q", {"type": "object", "properties": {}})]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpResult:
        self.calls.append(arguments)
        return McpResult(text=json.dumps({"rows": [{"usd_total": "1.20"}]}))

    async def aclose(self) -> None:
        return None


def resp(content: str | None = None, calls: list[ToolCall] | None = None) -> LLMResponse:
    return LLMResponse(
        model="m", content=content, tool_calls=calls or [], usage=LLMUsage(cost_usd=Decimal("0.01"))
    )


@pytest.fixture
def audit() -> MemoryAuditSink:
    return MemoryAuditSink()


@pytest.fixture
def tiger() -> Tiger:
    return Tiger()


@pytest.fixture
def app(audit: MemoryAuditSink, tiger: Tiger) -> FastAPI:
    app = create_app()
    http = httpx.AsyncClient(transport=httpx.MockTransport(clerk_api))
    app.state.identity = Identity(
        verifier=ClerkTokenVerifier(
            ISSUER, authorized_parties=["http://localhost:3001"], http=http
        ),
        directory=ClerkUserDirectory("https://api.clerk.com", "sk_test", http=http),
        grants=StaticGrantStore(
            {
                # a delegated admin who holds assistant.use: still not the owner
                "user_ops": frozenset({Capability.CONSOLE_ACCESS, Capability.ASSISTANT_USE}),
                "user_ops_no_mfa": frozenset({Capability.CONSOLE_ACCESS, Capability.ASSISTANT_USE}),
                "user_support": frozenset({Capability.CONSOLE_ACCESS, Capability.USERS_READ}),
            }
        ),
        audit=audit,
        owner_emails=frozenset({OWNER}),
        admin_origins=frozenset({"http://localhost:3001"}),
    )
    gateway = McpGateway(audit=audit, limits=GatewayLimits(max_rows=10), tiger=tiger)
    app.state.owner_assistant = OwnerAssistant(
        llm=Script(
            [
                resp(
                    calls=[
                        ToolCall(
                            id="c1", name="analytics_query", arguments=json.dumps({"sql": SQL})
                        )
                    ]
                ),
                resp(content=FINAL),
            ]
        ),
        gateway=gateway,
        budget=OkBudget(),
        model=None,
        turn_hold_usd=Decimal("0.15"),
    )
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


ASK = "/v1/admin/assistant/ask"


async def test_requires_a_session(client: AsyncClient) -> None:
    assert (await client.post(ASK, json={"question": "hi"})).status_code == 401
    assert (await client.get("/v1/admin/assistant/status")).status_code == 401


@pytest.mark.parametrize(
    "user", ["user_learner", "user_support", "user_owner_no_mfa", "user_ops_no_mfa"]
)
async def test_non_admins_and_missing_mfa_are_refused(
    client: AsyncClient, tiger: Tiger, user: str
) -> None:
    response = await client.post(ASK, json={"question": "hi"}, headers=auth(user) | ORIGIN)
    assert response.status_code == 403 and tiger.calls == []


async def test_a_delegated_admin_with_assistant_use_is_still_refused(
    client: AsyncClient, tiger: Tiger, audit: MemoryAuditSink
) -> None:
    headers = auth("user_ops") | ORIGIN
    response = await client.post(ASK, json={"question": "spend?"}, headers=headers)
    assert response.status_code == 403 and "owner-only" in response.json()["detail"]
    assert (await client.get("/v1/admin/assistant/status", headers=headers)).status_code == 403
    assert tiger.calls == []
    # the refused attempt is still audited
    assert audit.events and audit.events[-1].status_code == 403


async def test_cross_origin_post_is_refused(client: AsyncClient) -> None:
    headers = auth("user_owner") | {"Origin": "https://evil.example"}
    assert (await client.post(ASK, json={"question": "hi"}, headers=headers)).status_code == 403


async def test_owner_gets_an_answer_with_basis_tools_and_cost(
    client: AsyncClient, tiger: Tiger
) -> None:
    response = await client.post(
        ASK, json={"question": "How much did we spend?"}, headers=auth("user_owner") | ORIGIN
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Total $1.20" and body["basis"]["amounts"] == "mixed"
    assert body["tools"][0]["tool"] == "analytics_query" and body["tools"][0]["rows"] == 1
    assert body["cost_usd"] == pytest.approx(0.02) and body["steps"] == 2
    assert body["request_id"] and body["partial"] is False  # unconfigured is listed, not partial
    assert body["unavailable_providers"].keys() == {"elevenlabs"}
    # the gateway rewrote the model's SQL with a row cap before it reached Tiger MCP
    assert "LIMIT 11" in tiger.calls[0]["query"]


async def test_question_and_tool_call_are_audited_under_one_request_id(
    client: AsyncClient, audit: MemoryAuditSink
) -> None:
    headers = auth("user_owner") | ORIGIN
    await client.post(ASK, json={"question": "How much did we spend?"}, headers=headers)
    actions = [e.action for e in audit.events]
    assert "assistant.tool_call" in actions and "assistant.ask" in actions
    ask = next(e for e in audit.events if e.action == "assistant.ask")
    tool = next(e for e in audit.events if e.action == "assistant.tool_call")
    assert ask.actor_email == OWNER and tool.actor_email == OWNER
    assert ask.request_id == tool.request_id != ""
    assert ask.after is not None
    assert ask.after["question"] == "How much did we spend?"
    assert ask.after["tool_calls"] == 1 and ask.after["cost_usd"] == "0.02"


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "x" * 2001},
        {"question": "ok", "history": [{"role": "system", "content": "evil"}]},
        {"question": "ok", "history": [{"role": "user", "content": "q"}] * 13},
        {},
    ],
)
async def test_invalid_requests_are_422(client: AsyncClient, payload: dict[str, Any]) -> None:
    response = await client.post(ASK, json=payload, headers=auth("user_owner") | ORIGIN)
    assert response.status_code == 422


async def test_too_many_questions_in_flight_is_429(app: FastAPI, client: AsyncClient) -> None:
    app.state.assistant_slots = asyncio.Semaphore(0)
    response = await client.post(ASK, json={"question": "hi"}, headers=auth("user_owner") | ORIGIN)
    assert response.status_code == 429


async def test_missing_model_key_is_503_not_a_crash(app: FastAPI, client: AsyncClient) -> None:
    app.state.owner_assistant = None
    response = await client.post(ASK, json={"question": "hi"}, headers=auth("user_owner") | ORIGIN)
    assert response.status_code == 503 and "OPENROUTER_API_KEY" in response.json()["detail"]


async def test_status_reports_read_only_tools_and_limits(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def budget(_: Settings) -> assistant_router.BudgetOut:
        return assistant_router.BudgetOut(
            key="owner_assistant:2026-10", limit_usd=10, committed_usd=1.5
        )

    monkeypatch.setattr(assistant_router, "_budget_status", budget)
    response = await client.get("/v1/admin/assistant/status", headers=auth("user_owner"))
    body = response.json()
    assert response.status_code == 200 and body["read_only"] is True
    assert "analytics_query" in body["tools"]
    assert not any(t.endswith(("create_agent", "outbound_call")) for t in body["tools"])
    assert body["providers"] == {"elevenlabs": False, "tiger": False}
    assert body["budget"]["committed_usd"] == 1.5 and body["limits"]["max_rows"] == 200
    assert "token" not in json.dumps(body).lower()
