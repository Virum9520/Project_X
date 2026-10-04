"""Processing of stored provider events (no Hatchet imports: unit-testable with a DB only).

Handlers are registered per (provider, event_type). Later components plug in here, for example C11
registers `elevenlabs` / `post_call_transcription` to start the evidence pipeline.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.models.enums import ProviderEventStatus
from sg_core.models.sessions import ProviderEvent

log = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, ProviderEvent], Awaitable[None]]

_TERMINAL = (ProviderEventStatus.PROCESSED, ProviderEventStatus.IGNORED)
MAX_ERROR_CHARS = 2000


class ProcessOutcome(StrEnum):
    PROCESSED = "processed"
    IGNORED = "ignored"
    SKIPPED = "skipped"  # already terminal or missing
    FAILED = "failed"


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], Handler] = {}

    def register(self, provider: str, event_type: str) -> Callable[[Handler], Handler]:
        def decorator(fn: Handler) -> Handler:
            self._handlers[(provider, event_type)] = fn
            return fn

        return decorator

    def get(self, provider: str, event_type: str) -> Handler | None:
        return self._handlers.get((provider, event_type))


handlers = HandlerRegistry()


async def process_provider_event(
    session: AsyncSession,
    provider_event_id: uuid.UUID,
    registry: HandlerRegistry = handlers,
) -> ProcessOutcome:
    """Run the handler exactly-once-effective for a stored event.

    The row is locked (FOR UPDATE) for the whole run, so concurrent or duplicate jobs cannot both
    execute the handler, and terminal rows are never reprocessed. The lock blocks rather than
    skipping: a run that starts while ingest still holds the row (between dispatch and the ENQUEUED
    update) waits for that commit instead of returning early and leaving the event unprocessed.
    Handler writes commit together with the status change. On error the handler's writes roll
    back, the failure is recorded, and the exception is re-raised so the job system can retry.
    """
    event = (
        await session.execute(
            select(ProviderEvent).where(ProviderEvent.id == provider_event_id).with_for_update()
        )
    ).scalar_one_or_none()
    if event is None or event.status in _TERMINAL:
        await session.rollback()
        return ProcessOutcome.SKIPPED

    handler = registry.get(event.provider, event.event_type)
    if handler is None:
        event.status = ProviderEventStatus.IGNORED
        event.processed_at = datetime.now(UTC)
        await session.commit()
        return ProcessOutcome.IGNORED

    try:
        async with session.begin_nested():
            await handler(session, event)
    except Exception as exc:
        await session.refresh(event)  # the savepoint rollback expired it
        event.status = ProviderEventStatus.FAILED
        event.attempts = event.attempts + 1
        event.error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
        await session.commit()
        log.exception(
            "provider event handler failed", extra={"provider_event_id": str(provider_event_id)}
        )
        raise
    event.status = ProviderEventStatus.PROCESSED
    event.attempts = event.attempts + 1
    event.error = None
    event.processed_at = datetime.now(UTC)
    await session.commit()
    return ProcessOutcome.PROCESSED


async def list_dead_letters(session: AsyncSession, limit: int = 100) -> list[ProviderEvent]:
    """Events that failed processing, oldest first. Backs the owner console's dead-letter view."""
    rows = await session.execute(
        select(ProviderEvent)
        .where(ProviderEvent.status == ProviderEventStatus.FAILED)
        .order_by(ProviderEvent.received_at)
        .limit(limit)
    )
    return list(rows.scalars())
