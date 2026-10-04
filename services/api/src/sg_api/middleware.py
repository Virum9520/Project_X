"""Request-scoped middleware: request IDs and access logging."""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

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
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return response


def _is_valid_request_id(value: str) -> bool:
    return 8 <= len(value) <= 64 and all(c.isalnum() or c in "-_" for c in value)
