import json
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from sg_core.identity import (
    ClerkTokenVerifier,
    ClerkUserDirectory,
    InvalidTokenError,
    UserDirectoryError,
)

ISSUER = "https://example.clerk.accounts.dev"
KID = "ins_test_key"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key())), "kid": KID}


def make_token(**overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "user_123",
        "sid": "sess_1",
        "azp": "http://localhost:3000",
        "iat": now,
        "nbf": now - 5,
        "exp": now + 60,
        "fva": [3, 3],
        "sts": "active",
        "v": 2,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})


class JwksServer:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/.well-known/jwks.json"
        self.calls += 1
        return httpx.Response(200, json={"keys": [JWK]})


def make_verifier(server: JwksServer) -> ClerkTokenVerifier:
    http = httpx.AsyncClient(transport=httpx.MockTransport(server))
    return ClerkTokenVerifier(ISSUER, authorized_parties=["http://localhost:3000"], http=http)


async def test_valid_token_yields_claims() -> None:
    server = JwksServer()
    claims = await make_verifier(server).verify(make_token())
    assert claims.user_id == "user_123"
    assert claims.session_id == "sess_1"
    assert claims.second_factor_verified


async def test_jwks_is_cached_between_requests() -> None:
    server = JwksServer()
    verifier = make_verifier(server)
    await verifier.verify(make_token())
    await verifier.verify(make_token())
    assert server.calls == 1


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"exp": int(time.time()) - 60}, "expired"),
        ({"iss": "https://evil.clerk.accounts.dev"}, "wrong issuer"),
        ({"azp": "https://evil.example"}, "foreign authorized party"),
        ({"sts": "pending"}, "pending session"),
        ({"sub": None}, "missing subject"),
    ],
)
async def test_rejects_bad_claims(overrides: dict[str, Any], reason: str) -> None:
    with pytest.raises(InvalidTokenError):
        await make_verifier(JwksServer()).verify(make_token(**overrides))


async def test_rejects_token_signed_by_another_key() -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {"iss": ISSUER, "sub": "u", "iat": 1, "nbf": 1, "exp": 2**31},
        other,
        algorithm="RS256",
        headers={"kid": KID},
    )
    with pytest.raises(InvalidTokenError):
        await make_verifier(JwksServer()).verify(token)


async def test_rejects_symmetric_algorithm() -> None:
    token = jwt.encode({"iss": ISSUER, "sub": "u"}, "s" * 32, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        await make_verifier(JwksServer()).verify(token)


async def test_unknown_kid_refresh_is_throttled() -> None:
    server = JwksServer()
    verifier = make_verifier(server)
    await verifier.verify(make_token())
    forged = jwt.encode(
        {"iss": ISSUER, "sub": "u"}, PRIVATE_KEY, algorithm="RS256", headers={"kid": "nope"}
    )
    for _ in range(3):
        with pytest.raises(InvalidTokenError):
            await verifier.verify(forged)
    assert server.calls == 1


def test_missing_fva_means_no_second_factor() -> None:
    from sg_core.identity import SessionClaims

    claims = SessionClaims("u", None, None, 0, None)
    assert not claims.second_factor_verified
    assert not SessionClaims("u", None, None, 0, (2, -1)).second_factor_verified


def clerk_user(email: str, *, verified: bool = True, mfa: bool = False) -> dict[str, Any]:
    return {
        "id": "user_123",
        "primary_email_address_id": "idn_1",
        "email_addresses": [
            {"id": "idn_0", "email_address": "other@example.com", "verification": None},
            {
                "id": "idn_1",
                "email_address": email,
                "verification": {"status": "verified" if verified else "unverified"},
            },
        ],
        "two_factor_enabled": mfa,
    }


async def test_user_directory_reads_verified_primary_email() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=clerk_user("Owner@Example.com", mfa=True))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    directory = ClerkUserDirectory("https://api.clerk.com", "sk_test_x", http=http)
    user = await directory.get("user_123")
    await directory.get("user_123")
    assert user.primary_email == "owner@example.com"
    assert user.two_factor_enabled
    assert len(calls) == 1
    assert calls[0].headers["Authorization"] == "Bearer sk_test_x"
    assert calls[0].url.path == "/v1/users/user_123"


async def test_user_directory_ignores_unverified_email() -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=clerk_user("owner@example.com", verified=False))
        )
    )
    user = await ClerkUserDirectory("https://api.clerk.com", "sk", http=http).get("user_123")
    assert user.primary_email is None


async def test_user_directory_errors_are_wrapped() -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    with pytest.raises(UserDirectoryError):
        await ClerkUserDirectory("https://api.clerk.com", "sk", http=http).get("user_123")
