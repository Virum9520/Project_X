"""Clerk session-token verification (JWKS) and user lookups (Backend API).

One Clerk application serves both the learner app and the owner console, so there is one issuer
and one JWKS. Session tokens are short-lived RS256 JWTs; we verify them locally against the cached
JWKS and only call the Backend API for facts the token does not carry (verified email, MFA state).
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
import jwt

ALGORITHMS = ["RS256"]
# Minimum gap between JWKS refreshes triggered by an unknown `kid`, so forged kids can't make us
# hammer Clerk.
_JWKS_MIN_REFRESH_SECONDS = 30.0


class InvalidTokenError(Exception):
    """The bearer token is missing, malformed, expired or not issued for us."""


class UserDirectoryError(Exception):
    """Clerk's Backend API could not tell us who the user is."""


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: str
    session_id: str | None
    authorized_party: str | None
    expires_at: int
    # Minutes since the first and second factor were verified; -1 means never in this session.
    factor_verification_age: tuple[int, int] | None

    @property
    def second_factor_verified(self) -> bool:
        return self.factor_verification_age is not None and self.factor_verification_age[1] >= 0


@dataclass(frozen=True, slots=True)
class ClerkUser:
    id: str
    primary_email: str | None
    """Lower-cased primary email, set only when Clerk has verified it."""
    two_factor_enabled: bool


class ClerkTokenVerifier:
    def __init__(
        self,
        issuer: str,
        *,
        authorized_parties: list[str],
        http: httpx.AsyncClient,
        jwks_ttl_seconds: float = 3600.0,
        leeway_seconds: float = 5.0,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._authorized_parties = {p.rstrip("/") for p in authorized_parties}
        self._http = http
        self._jwks_ttl = jwks_ttl_seconds
        self._leeway = leeway_seconds
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def jwks_url(self) -> str:
        return f"{self._issuer}/.well-known/jwks.json"

    async def verify(self, token: str) -> SessionClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed token") from exc
        kid = header.get("kid")
        if not isinstance(kid, str) or header.get("alg") not in ALGORITHMS:
            raise InvalidTokenError("unsupported token header")

        key = await self._key_for(kid)
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "nbf", "iss", "sub"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc

        azp = payload.get("azp")
        if azp is not None and azp.rstrip("/") not in self._authorized_parties:
            raise InvalidTokenError("unauthorized party")
        # Pending sessions still have sign-in tasks to finish; treat them as signed out.
        if payload.get("sts", "active") != "active":
            raise InvalidTokenError("session is not active")

        return SessionClaims(
            user_id=payload["sub"],
            session_id=payload.get("sid"),
            authorized_party=azp,
            expires_at=int(payload["exp"]),
            factor_verification_age=_parse_fva(payload.get("fva")),
        )

    async def _key_for(self, kid: str) -> Any:
        stale = time.monotonic() - self._fetched_at > self._jwks_ttl
        if kid in self._keys and not stale:
            return self._keys[kid]
        async with self._lock:
            since_fetch = time.monotonic() - self._fetched_at
            should_refresh = stale or (
                kid not in self._keys and since_fetch > _JWKS_MIN_REFRESH_SECONDS
            )
            if should_refresh:
                await self._refresh()
        if kid not in self._keys:
            raise InvalidTokenError("unknown signing key")
        return self._keys[kid]

    async def _refresh(self) -> None:
        try:
            response = await self._http.get(self.jwks_url)
            response.raise_for_status()
            jwk_set = jwt.PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, jwt.PyJWTError, ValueError) as exc:
            if self._keys:  # keep serving the last good set during a Clerk blip
                return
            raise InvalidTokenError("signing keys unavailable") from exc
        self._keys = {k.key_id: k.key for k in jwk_set.keys if k.key_id}
        self._fetched_at = time.monotonic()


class ClerkUserDirectory:
    """Reads users from Clerk's Backend API, with a short in-process cache."""

    def __init__(
        self,
        api_url: str,
        secret_key: str,
        *,
        http: httpx.AsyncClient,
        ttl_seconds: float = 60.0,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {secret_key}"}
        self._http = http
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, ClerkUser]] = {}

    async def get(self, user_id: str) -> ClerkUser:
        cached = self._cache.get(user_id)
        if cached and time.monotonic() - cached[0] < self._ttl:
            return cached[1]
        try:
            response = await self._http.get(
                f"{self._api_url}/v1/users/{quote(user_id, safe='')}", headers=self._headers
            )
            response.raise_for_status()
            user = _parse_user(response.json())
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise UserDirectoryError(f"could not load user {user_id}") from exc
        self._cache[user_id] = (time.monotonic(), user)
        return user


def _parse_fva(value: object) -> tuple[int, int] | None:
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) for v in value):
        return (value[0], value[1])
    return None


def _parse_user(data: dict[str, Any]) -> ClerkUser:
    primary_id = data.get("primary_email_address_id")
    primary_email: str | None = None
    for entry in data.get("email_addresses") or []:
        verified = (entry.get("verification") or {}).get("status") == "verified"
        if entry.get("id") == primary_id and verified:
            primary_email = str(entry["email_address"]).strip().lower()
    return ClerkUser(
        id=str(data["id"]),
        primary_email=primary_email,
        two_factor_enabled=bool(data.get("two_factor_enabled")),
    )
