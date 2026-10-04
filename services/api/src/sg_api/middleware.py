"""Request-scoped middleware: request IDs, access logging and admin audit records."""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from sg_api.auth.deps import AdminPrincipal, AuditDetails
from sg_core.identity import AuditEvent, SessionClaims

REQUEST_ID_HEADER = "X-Request-ID"

log = structlog.get_logger("sg_api.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID (or trusts a well-formed inbound one) and logs each request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        inbound = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = inbound if _is_valid_request_id(inbound) else uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "request",
            method=request.method,
            # The route template, never the raw path: path params carry signed share tokens.
            path=getattr(request.scope.get("route"), "path", None) or "<unmatched>",
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return response


def _is_valid_request_id(value: str) -> bool:
    return 8 <= len(value) <= 64 and all(c.isalnum() or c in "-_" for c in value)


ADMIN_PATH_PREFIX = "/v1/admin"
AUDITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AuditMiddleware(BaseHTTPMiddleware):
    """Writes an audit record for every admin mutation, including refused ones.

    The actor comes from the auth dependencies (`request.state.admin_principal`, or just the
    verified session when admin checks refused it). Handlers add target and before/after state
    with `sg_api.auth.record_audit`. Unauthenticated requests are only access-logged.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.method in AUDITED_METHODS and request.url.path.startswith(ADMIN_PATH_PREFIX):
            await _write_audit(request, response.status_code)
        return response


async def _write_audit(request: Request, status_code: int) -> None:
    principal: AdminPrincipal | None = getattr(request.state, "admin_principal", None)
    claims: SessionClaims | None = getattr(request.state, "session_claims", None)
    if principal is not None:
        actor_id, actor_email = principal.user_id, principal.email
    elif claims is not None:
        actor_id, actor_email = claims.user_id, None
    else:
        return
    details: AuditDetails = getattr(request.state, "audit", None) or AuditDetails()
    route = request.scope.get("route")
    event = AuditEvent(
        actor_id=actor_id,
        actor_email=actor_email,
        action=details.action or f"{request.method} {getattr(route, 'path', request.url.path)}",
        request_id=getattr(request.state, "request_id", ""),
        status_code=status_code,
        target=details.target,
        before=details.before,
        after=details.after,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    try:
        await request.app.state.identity.audit.record(event)
    except Exception as exc:  # an audit sink failure must be loud but not change the response
        log.error("audit.write_failed", error=str(exc), action=event.action)
