"""FastAPI dependencies: who is calling, and may they do this?

- `current_session`: any signed-in Clerk user (learner routes).
- `current_admin`: owner allowlist or capability grant, verified email, and a session that passed
  a second factor. Anyone else is refused here, whatever the frontend shows.
- `require_capability(cap)`: admin plus one specific capability.
- `admin_origin_guard`: CSRF origin check for admin mutations.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status

from sg_api.auth.context import Identity
from sg_core.identity import (
    OWNER_CAPABILITIES,
    Capability,
    ClerkUser,
    InvalidTokenError,
    SessionClaims,
    UserDirectoryError,
)
from sg_core.logging import get_logger

log = get_logger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    user_id: str
    email: str
    is_owner: bool
    capabilities: frozenset[Capability]
    claims: SessionClaims

    def can(self, capability: Capability) -> bool:
        return capability in self.capabilities


@dataclass(slots=True)
class AuditDetails:
    action: str | None = None
    target: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


def get_identity(request: Request) -> Identity:
    identity: Identity = request.app.state.identity
    return identity


IdentityDep = Annotated[Identity, Depends(get_identity)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def current_session(request: Request, identity: IdentityDep) -> SessionClaims:
    if identity.verifier is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "authentication not configured")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("missing bearer token")
    try:
        claims = await identity.verifier.verify(token.strip())
    except InvalidTokenError as exc:
        log.info("auth.token_rejected", reason=str(exc))
        raise _unauthorized("invalid token") from exc
    request.state.session_claims = claims
    return claims


SessionDep = Annotated[SessionClaims, Depends(current_session)]


async def load_user(identity: Identity, user_id: str) -> ClerkUser:
    if identity.directory is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "user directory not configured")
    try:
        return await identity.directory.get(user_id)
    except UserDirectoryError as exc:
        log.warning("auth.user_lookup_failed", user_id=user_id, error=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "user lookup failed") from exc


async def capabilities_of(
    identity: Identity, user: ClerkUser
) -> tuple[bool, frozenset[Capability]]:
    """Owners (verified primary email on the allowlist) get everything; others get their grants."""
    is_owner = user.primary_email is not None and user.primary_email in identity.owner_emails
    if is_owner:
        return True, OWNER_CAPABILITIES
    try:
        return False, await identity.grants.capabilities_for(user.id)
    except Exception as exc:  # grant store down: deny rather than guess
        log.error("auth.grants_lookup_failed", user_id=user.id, error=str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "grant lookup failed") from exc


async def sync_user(identity: Identity, user: ClerkUser) -> None:
    """Mirror the Clerk user into our tables. Best effort: a database blip must not break auth."""
    try:
        await identity.users.sync(user)
    except Exception as exc:
        log.warning("auth.user_sync_failed", user_id=user.id, error=str(exc))


async def current_admin(
    request: Request, identity: IdentityDep, claims: SessionDep
) -> AdminPrincipal:
    user = await load_user(identity, claims.user_id)
    await sync_user(identity, user)  # so grants and audit rows can reference the user
    is_owner, capabilities = await capabilities_of(identity, user)
    if user.primary_email is None or Capability.CONSOLE_ACCESS not in capabilities:
        log.warning("auth.admin_denied", user_id=user.id, reason="not_allowlisted")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not an owner-console user")
    if not (user.two_factor_enabled and claims.second_factor_verified):
        log.warning("auth.admin_denied", user_id=user.id, reason="mfa_required")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "multi-factor authentication required")
    principal = AdminPrincipal(
        user_id=user.id,
        email=user.primary_email,
        is_owner=is_owner,
        capabilities=capabilities,
        claims=claims,
    )
    request.state.admin_principal = principal
    return principal


AdminDep = Annotated[AdminPrincipal, Depends(current_admin)]


def require_capability(capability: Capability) -> Callable[..., Awaitable[AdminPrincipal]]:
    async def dependency(principal: AdminDep) -> AdminPrincipal:
        if not principal.can(capability):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing capability {capability}")
        return principal

    return dependency


async def admin_origin_guard(request: Request, identity: IdentityDep) -> None:
    """Reject cross-site admin mutations.

    Admin calls authenticate with a bearer token, which browsers never attach on their own, so this
    is defence in depth: a browser-sent mutation must come from an owner-console origin. Requests
    without Origin or Referer (server-to-server from the console's own backend) pass through.
    """
    if request.method in SAFE_METHODS:
        return
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-site request refused")
    origin = request.headers.get("Origin") or _origin_of(request.headers.get("Referer"))
    if origin is not None and origin.rstrip("/") not in identity.admin_origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin not allowed")


def _origin_of(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else "null"


def record_audit(
    request: Request,
    *,
    action: str | None = None,
    target: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Attach what an admin mutation changed; `AuditMiddleware` writes it after the response."""
    request.state.audit = AuditDetails(action=action, target=target, before=before, after=after)
