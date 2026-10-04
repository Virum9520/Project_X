import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from sg_api.auth import Identity, admin_origin_guard, record_audit, require_capability
from sg_api.main import create_app
from sg_core.identity import (
    AuditEvent,
    Capability,
    ClerkTokenVerifier,
    ClerkUser,
    ClerkUserDirectory,
    StaticGrantStore,
)

ISSUER = "https://example.clerk.accounts.dev"
KID = "ins_test_key"
OWNER = "owner@example.com"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key())), "kid": KID}

# user id -> (primary email, email verified, two-factor enabled)
USERS: dict[str, tuple[str, bool, bool]] = {
    "user_owner": (OWNER, True, True),
    "user_owner_no_mfa": (OWNER, True, False),
    "user_owner_unverified": (OWNER, False, True),
    "user_learner": ("learner@example.com", True, False),
    "user_support": ("support@example.com", True, True),
}


def token_for(user_id: str, *, fva: list[int] | None = None) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": user_id,
        "sid": "sess_1",
        "azp": "http://localhost:3001",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "fva": fva if fva is not None else [1, 1],
        "sts": "active",
    }
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})


def auth(user_id: str, **kwargs: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user_id, **kwargs)}"}


def clerk_api(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/.well-known/jwks.json":
        return httpx.Response(200, json={"keys": [JWK]})
    user_id = request.url.path.rsplit("/", 1)[-1]
    if user_id not in USERS:
        return httpx.Response(404)
    email, verified, mfa = USERS[user_id]
    return httpx.Response(
        200,
        json={
            "id": user_id,
            "primary_email_address_id": "idn_1",
            "email_addresses": [
                {
                    "id": "idn_1",
                    "email_address": email,
                    "verification": {"status": "verified" if verified else "unverified"},
                }
            ],
            "two_factor_enabled": mfa,
        },
    )


class MemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


@pytest.fixture
def audit() -> MemoryAuditSink:
    return MemoryAuditSink()


@pytest.fixture
def app(audit: MemoryAuditSink) -> FastAPI:
    app = create_app()
    http = httpx.AsyncClient(transport=httpx.MockTransport(clerk_api))
    app.state.identity = Identity(
        verifier=ClerkTokenVerifier(
            ISSUER, authorized_parties=["http://localhost:3000", "http://localhost:3001"], http=http
        ),
        directory=ClerkUserDirectory("https://api.clerk.com", "sk_test", http=http),
        grants=StaticGrantStore(
            {"user_support": frozenset({Capability.CONSOLE_ACCESS, Capability.USERS_READ})}
        ),
        audit=audit,
        owner_emails=frozenset({OWNER}),
        admin_origins=frozenset({"http://localhost:3001"}),
    )

    @app.post(
        "/v1/admin/test-mutation/{item}",
        dependencies=[
            Depends(admin_origin_guard),
            Depends(require_capability(Capability.USERS_WRITE)),
        ],
    )
    async def mutate(item: str, request: Request) -> dict[str, str]:
        record_audit(request, target=f"item:{item}", before={"v": 1}, after={"v": 2})
        return {"ok": item}

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_me_requires_a_bearer_token(client: AsyncClient) -> None:
    response = await client.get("/v1/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_me_rejects_a_garbage_token(client: AsyncClient) -> None:
    response = await client.get("/v1/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_learner_sees_no_console_access(client: AsyncClient) -> None:
    response = await client.get("/v1/me", headers=auth("user_learner"))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "learner@example.com"
    assert body["console_access"] is False
    assert body["capabilities"] == []


async def test_owner_has_every_capability(client: AsyncClient) -> None:
    response = await client.get("/v1/admin/me", headers=auth("user_owner"))
    assert response.status_code == 200
    body = response.json()
    assert body["is_owner"] is True
    assert body["mfa_verified"] is True
    assert set(body["capabilities"]) == {c.value for c in Capability}


@pytest.mark.parametrize(
    ("user_id", "fva", "detail"),
    [
        ("user_learner", None, "not an owner-console user"),
        ("user_owner_unverified", None, "not an owner-console user"),
        ("user_owner_no_mfa", None, "multi-factor authentication required"),
        ("user_owner", [1, -1], "multi-factor authentication required"),
    ],
)
async def test_admin_refusals(
    client: AsyncClient, user_id: str, fva: list[int] | None, detail: str
) -> None:
    response = await client.get("/v1/admin/me", headers=auth(user_id, fva=fva))
    assert response.status_code == 403
    assert response.json()["detail"] == detail


async def test_granted_admin_gets_only_granted_capabilities(client: AsyncClient) -> None:
    response = await client.get("/v1/admin/me", headers=auth("user_support"))
    assert response.status_code == 200
    assert response.json()["is_owner"] is False
    assert set(response.json()["capabilities"]) == {"console.access", "users.read"}

    denied = await client.post("/v1/admin/test-mutation/a", headers=auth("user_support"))
    assert denied.status_code == 403
    assert denied.json()["detail"] == "missing capability users.write"


async def test_admin_mutation_is_audited(client: AsyncClient, audit: MemoryAuditSink) -> None:
    response = await client.post(
        "/v1/admin/test-mutation/42",
        headers={
            **auth("user_owner"),
            "Origin": "http://localhost:3001",
            "X-Request-ID": "req-123456",
        },
    )
    assert response.status_code == 200
    [event] = audit.events
    assert event.actor_id == "user_owner"
    assert event.actor_email == OWNER
    assert event.action == "POST /v1/admin/test-mutation/{item}"
    assert event.target == "item:42"
    assert (event.before, event.after) == ({"v": 1}, {"v": 2})
    assert event.request_id == "req-123456"
    assert event.status_code == 200


async def test_refused_admin_mutation_is_audited_too(
    client: AsyncClient, audit: MemoryAuditSink
) -> None:
    response = await client.post("/v1/admin/test-mutation/42", headers=auth("user_learner"))
    assert response.status_code == 403
    [event] = audit.events
    assert event.actor_id == "user_learner"
    assert event.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Referer": "https://evil.example/page"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
async def test_cross_site_admin_mutations_are_refused(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.post(
        "/v1/admin/test-mutation/1", headers={**auth("user_owner"), **headers}
    )
    assert response.status_code == 403


async def test_unauthenticated_admin_mutation_is_not_audited(
    client: AsyncClient, audit: MemoryAuditSink
) -> None:
    response = await client.post("/v1/admin/test-mutation/1")
    assert response.status_code == 401
    assert audit.events == []


async def test_auth_unconfigured_answers_503(app: FastAPI, client: AsyncClient) -> None:
    app.state.identity.verifier = None
    response = await client.get("/v1/me", headers=auth("user_learner"))
    assert response.status_code == 503


class RecordingUserStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.synced: list[str] = []
        self._fail = fail

    async def sync(self, user: ClerkUser) -> None:
        if self._fail:
            raise RuntimeError("db down")
        self.synced.append(user.id)


async def test_me_and_admin_sync_the_user(app: FastAPI, client: AsyncClient) -> None:
    store = RecordingUserStore()
    app.state.identity.users = store
    assert (await client.get("/v1/me", headers=auth("user_learner"))).status_code == 200
    assert (await client.get("/v1/admin/me", headers=auth("user_owner"))).status_code == 200
    assert store.synced == ["user_learner", "user_owner"]


async def test_user_sync_failure_does_not_break_auth(app: FastAPI, client: AsyncClient) -> None:
    app.state.identity.users = RecordingUserStore(fail=True)
    assert (await client.get("/v1/me", headers=auth("user_learner"))).status_code == 200


async def test_grant_store_failure_denies_with_503(app: FastAPI, client: AsyncClient) -> None:
    class BrokenGrants:
        async def capabilities_for(self, user_id: str) -> frozenset[Capability]:
            raise RuntimeError("db down")

    app.state.identity.grants = BrokenGrants()
    response = await client.get("/v1/admin/me", headers=auth("user_support"))
    assert response.status_code == 503
    # Owners never depend on the grant store.
    assert (await client.get("/v1/admin/me", headers=auth("user_owner"))).status_code == 200
