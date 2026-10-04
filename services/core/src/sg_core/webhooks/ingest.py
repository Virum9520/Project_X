"""Store-first, idempotent webhook ingestion.

Order matters: verify signature -> persist raw event (unique per provider event id) -> dispatch.
A duplicate delivery never re-dispatches an event that was already enqueued or processed. If
dispatch fails the row stays `received`, so the provider's retry (or a sweep) can dispatch it
later, and the caller still acknowledges with 2xx because the event is durable.
"""

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.models.enums import ProviderEventStatus
from sg_core.models.sessions import ProviderEvent
from sg_core.webhooks.verifiers import VerifierRegistry

log = logging.getLogger(__name__)


class Dispatcher(Protocol):
    async def dispatch(self, provider_event_id: uuid.UUID, provider: str, event_type: str) -> None:
        """Hand a stored event to the job system. Must be safe to call twice."""


class IngestOutcome(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class IngestResult:
    outcome: IngestOutcome
    provider_event_id: uuid.UUID
    dispatched: bool


async def ingest_webhook(
    session: AsyncSession,
    registry: VerifierRegistry,
    dispatcher: Dispatcher,
    *,
    provider: str,
    headers: Mapping[str, str],
    body: bytes,
) -> IngestResult:
    """Raises UnknownProviderError / SignatureError before anything is stored."""
    verifier = registry.get(provider)
    verifier.verify(headers, body)
    event = verifier.parse(body)

    stmt = (
        insert(ProviderEvent)
        .values(
            provider=provider,
            event_id=event.event_id,
            event_type=event.event_type,
            signature_verified=True,
            payload=event.payload,
        )
        .on_conflict_do_nothing(index_elements=["provider", "event_id"])
        .returning(ProviderEvent.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()  # durable before we touch the queue

    if inserted is None:
        row = (
            await session.execute(
                select(ProviderEvent.id, ProviderEvent.status).where(
                    ProviderEvent.provider == provider, ProviderEvent.event_id == event.event_id
                )
            )
        ).one()
        if row.status is not ProviderEventStatus.RECEIVED:
            return IngestResult(IngestOutcome.DUPLICATE, row.id, dispatched=False)
        # An earlier delivery was stored but never dispatched: dispatch now.
        event_row_id, outcome = row.id, IngestOutcome.DUPLICATE
    else:
        event_row_id, outcome = inserted, IngestOutcome.ACCEPTED

    try:
        await dispatcher.dispatch(event_row_id, provider, event.event_type)
    except Exception:
        log.exception("webhook dispatch failed; event stays received", extra={"provider": provider})
        return IngestResult(outcome, event_row_id, dispatched=False)
    await mark_event(
        session,
        event_row_id,
        ProviderEventStatus.ENQUEUED,
        only_from=(ProviderEventStatus.RECEIVED,),
    )
    return IngestResult(outcome, event_row_id, dispatched=True)


async def mark_event(
    session: AsyncSession,
    event_id: uuid.UUID,
    status: ProviderEventStatus,
    *,
    only_from: tuple[ProviderEventStatus, ...] | None = None,
    error: str | None = None,
    count_attempt: bool = False,
) -> bool:
    """Compare-and-set a status transition. Returns False when the guard did not match."""
    values: dict[str, Any] = {"status": status, "error": error}
    if status in (ProviderEventStatus.PROCESSED, ProviderEventStatus.IGNORED):
        values["processed_at"] = datetime.now(UTC)
    if count_attempt:
        values["attempts"] = ProviderEvent.attempts + 1
    stmt = update(ProviderEvent).where(ProviderEvent.id == event_id).values(**values)
    if only_from:
        stmt = stmt.where(ProviderEvent.status.in_(only_from))
    result = await session.execute(stmt)
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]
