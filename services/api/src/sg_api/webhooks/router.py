"""Public provider webhook endpoint: `POST /v1/webhooks/{provider}`.

No auth dependency: the provider signature is the authentication. The raw body is read before any
parsing because the signature covers the exact bytes.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.db import session_scope
from sg_core.settings import get_settings
from sg_core.webhooks import (
    Dispatcher,
    SignatureError,
    UnknownProviderError,
    VerifierRegistry,
    default_registry,
    ingest_webhook,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


def get_registry(request: Request) -> VerifierRegistry:
    registry: VerifierRegistry | None = getattr(request.app.state, "webhook_registry", None)
    if registry is None:
        registry = request.app.state.webhook_registry = default_registry(get_settings())
    return registry


def get_dispatcher(request: Request) -> Dispatcher:
    dispatcher: Dispatcher | None = getattr(request.app.state, "webhook_dispatcher", None)
    if dispatcher is None:
        from sg_worker.dispatch import HatchetDispatcher

        dispatcher = request.app.state.webhook_dispatcher = HatchetDispatcher()
    return dispatcher


@router.post("/{provider}", status_code=202)
async def receive_webhook(
    provider: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(session_scope)],
    registry: Annotated[VerifierRegistry, Depends(get_registry)],
    dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
) -> dict[str, str]:
    body = await request.body()
    try:
        result = await ingest_webhook(
            session,
            registry,
            dispatcher,
            provider=provider,
            headers=request.headers,
            body=body,
        )
    except UnknownProviderError:
        raise HTTPException(status_code=404, detail="unknown provider") from None
    except SignatureError as exc:
        # Reason is logged, never returned: don't give a forger an oracle.
        log.warning("webhook rejected", extra={"provider": provider, "reason": str(exc)})
        raise HTTPException(status_code=401, detail="invalid signature") from None
    return {"status": result.outcome.value, "id": str(result.provider_event_id)}
