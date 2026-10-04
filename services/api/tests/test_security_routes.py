"""Security sweep over every route the API publishes (C23, docs/security-review.md).

The route inventory comes from the OpenAPI schema, so a new endpoint is classified automatically:
`/v1/admin/*` must refuse learners, `/v1/agent-tools/*` must demand a session tool token, learner
routes must demand a Clerk session, and anything else must be on the explicit public list. A new
route that fits none of these fails `test_every_route_is_classified` until it is reviewed.
"""

import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from test_auth import KID, app, audit, auth  # noqa: F401  (`app`, `audit`: fixtures from test_auth)

from sg_api.sessions.tool_tokens import HEADER, mint_tool_token
from sg_core.settings import Environment, Settings, get_settings

assert KID

ADMIN_ORIGIN = {"Origin": "http://localhost:3001"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# Reachable without a user session, each for a stated reason.
PUBLIC = {
    "/healthz": "liveness probe",
    "/readyz": "readiness probe",
    "/v1/recap/shared/{token}": "signed share link: the token is the credential",
    "/v1/webhooks/{provider}": "provider webhook: HMAC-verified, stored first",
}
SETTINGS = Settings(  # type: ignore[call-arg]
    _env_file=None,
    environment=Environment.PROD,
    agent_tool_token_secret=SecretStr("s" * 48),
)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def operations(application: FastAPI) -> list[tuple[str, str]]:
    schema = application.openapi()
    return [
        (method.upper(), path)
        for path, item in sorted(schema["paths"].items())
        for method in item
        if method in HTTP_METHODS
    ]


def fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _m: str(uuid.uuid4()), path)


def kind(path: str) -> str:
    if path in PUBLIC:
        return "public"
    if path.startswith("/v1/admin"):
        return "admin"
    if path.startswith("/v1/agent-tools/"):
        return "agent-tool"
    if path.startswith("/v1/"):
        return "learner"
    return "unclassified"


async def call(client: AsyncClient, method: str, path: str, **kw: Any) -> int:
    # A body that would fail validation, so only an auth check can answer 401/403 first.
    response = await client.request(method, fill(path), json={}, **kw)
    return response.status_code


def test_every_route_is_classified(app: FastAPI) -> None:  # noqa: F811
    assert [op for op in operations(app) if kind(op[1]) == "unclassified"] == []
    assert {p for _, p in operations(app)} >= set(PUBLIC)


async def test_admin_routes_refuse_anonymous_and_learner_tokens(
    app: FastAPI,  # noqa: F811
    client: AsyncClient,
) -> None:
    admin_ops = [op for op in operations(app) if kind(op[1]) == "admin"]
    assert len(admin_ops) >= 15  # guards against the sweep silently covering nothing
    for method, path in admin_ops:
        anonymous = await call(client, method, path, headers=ADMIN_ORIGIN)
        assert anonymous == 401, f"{method} {path} answered {anonymous} without a token"
        learner = await call(client, method, path, headers={**auth("user_learner"), **ADMIN_ORIGIN})
        assert learner == 403, f"{method} {path} answered {learner} to a learner token"


async def test_admin_routes_refuse_an_owner_without_mfa(
    app: FastAPI,  # noqa: F811
    client: AsyncClient,
) -> None:
    for method, path in (op for op in operations(app) if kind(op[1]) == "admin"):
        status = await call(
            client, method, path, headers={**auth("user_owner_no_mfa"), **ADMIN_ORIGIN}
        )
        assert status == 403, f"{method} {path} answered {status} to an owner without MFA"


async def test_admin_mutations_refuse_cross_site_requests_even_for_the_owner(
    app: FastAPI,  # noqa: F811
    client: AsyncClient,
) -> None:
    mutations = [op for op in operations(app) if kind(op[1]) == "admin" and op[0] != "GET"]
    assert mutations
    for method, path in mutations:
        status = await call(
            client, method, path, headers={**auth("user_owner"), "Origin": "https://evil.example"}
        )
        assert status == 403, f"{method} {path} answered {status} to a cross-site origin"


async def test_learner_routes_require_a_session(
    app: FastAPI,  # noqa: F811
    client: AsyncClient,
) -> None:
    learner_ops = [op for op in operations(app) if kind(op[1]) == "learner"]
    assert len(learner_ops) >= 40
    for method, path in learner_ops:
        assert await call(client, method, path) == 401, f"{method} {path} is open"
        garbage = await call(client, method, path, headers={"Authorization": "Bearer nope"})
        assert garbage == 401, f"{method} {path} accepted a garbage token"


async def test_dev_identity_header_is_ignored_outside_a_dev_machine(
    app: FastAPI,  # noqa: F811
    client: AsyncClient,
) -> None:
    # SETTINGS is PROD: `X-Dev-User-Id` must not stand in for a Clerk session anywhere.
    for method, path in (op for op in operations(app) if kind(op[1]) == "learner"):
        status = await call(client, method, path, headers={"X-Dev-User-Id": "someone-else"})
        assert status == 401, f"{method} {path} trusted X-Dev-User-Id"


def test_hosted_platform_disables_dev_identity_even_if_environment_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = Settings(_env_file=None, environment=Environment.LOCAL)  # type: ignore[call-arg]
    for name in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_NAME", "VERCEL", "VERCEL_ENV"):
        monkeypatch.delenv(name, raising=False)
    assert local.dev_identity_allowed
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "prj_123")
    assert not local.dev_identity_allowed


async def test_agent_tools_demand_a_valid_session_tool_token(
    app: FastAPI,  # noqa: F811
    client: AsyncClient,
) -> None:
    tool_ops = [op for op in operations(app) if kind(op[1]) == "agent-tool"]
    assert len(tool_ops) >= 8
    forged, _ = mint_tool_token(
        user_id="u1",
        session_id="s1",
        character="drona",
        conversation_id="conv_1",
        settings=Settings(  # type: ignore[call-arg]
            _env_file=None, agent_tool_token_secret=SecretStr("x" * 48)
        ),
    )
    expired, _ = mint_tool_token(
        user_id="u1",
        session_id="s1",
        character="drona",
        conversation_id="conv_1",
        settings=SETTINGS,
        now=1_000_000,
    )
    for method, path in tool_ops:
        cases = {
            "no token": {},
            "a Clerk learner session": auth("user_learner"),
            "a token signed with another secret": {HEADER: forged},
            "an expired token": {HEADER: expired},
            "garbage": {HEADER: "not-a-token"},
        }
        for label, headers in cases.items():
            status = await call(client, method, path, headers=headers)
            assert status == 401, f"{method} {path} answered {status} to {label}"


async def test_a_tool_token_is_not_a_user_session(app: FastAPI, client: AsyncClient) -> None:  # noqa: F811
    token, _ = mint_tool_token(
        user_id="user_learner",
        session_id="s1",
        character="drona",
        conversation_id="conv_1",
        settings=SETTINGS,
    )
    for path in ("/v1/me", "/v1/garden/snapshot", "/v1/admin/me"):
        response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        response = await client.get(path, headers={HEADER: token})
        assert response.status_code == 401


async def test_unknown_webhook_provider_and_unsigned_bodies_are_rejected(
    client: AsyncClient,
) -> None:
    status = await client.post("/v1/webhooks/not-a-provider", content=b"{}")
    assert status.status_code in (400, 404)
    status = await client.post("/v1/webhooks/elevenlabs", content=b'{"type": "x"}')
    assert status.status_code in (400, 401, 403, 503)


async def test_access_log_never_contains_share_tokens(
    client: AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await client.get("/v1/recap/shared/SECRET.SIGNED.TOKEN")
    out = capsys.readouterr().out
    assert "path" in out and "SECRET" not in out
    assert "/v1/recap/shared/{token}" in out
