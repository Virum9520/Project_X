"""Usage ledger: one idempotent `usage_events` row plus its `cost_entries` row per provider call."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_core.db import get_sessionmaker
from sg_core.economics.pricing import MICRO, CostEstimate, PriceBook
from sg_core.economics.usage import UsageContext, UsageMeasure
from sg_core.models.economics import CostEntry, UsageEvent
from sg_core.models.enums import CostKind

log = structlog.get_logger(__name__)

SECONDS_PER_MINUTE = Decimal(60)


@dataclass(frozen=True, slots=True)
class LedgerResult:
    usage_event_id: uuid.UUID
    cost_entry_id: uuid.UUID | None
    duplicate: bool = False


def estimate_measure(
    measure: UsageMeasure, prices: PriceBook, at: datetime | None = None
) -> CostEstimate | None:
    """Estimate USD for a measure from the price book; None when it cannot be priced."""
    provider = measure.provider
    quantities: list[tuple[str, Decimal | int | None]] = []
    if provider == "elevenlabs":
        if measure.connected_seconds is not None:
            quantities.append(("agent_minute", measure.connected_seconds / SECONDS_PER_MINUTE))
        if measure.billable_unit and measure.billable_units is not None:
            quantities.append((measure.billable_unit, measure.billable_units))
    elif provider == "e2b":
        quantities.append(("sandbox_second", measure.sandbox_seconds))
    elif measure.model and (measure.input_tokens is not None or measure.output_tokens is not None):
        # Provider input_tokens include cached tokens; price the cached part at its own rate.
        cached = (measure.cache_read_tokens or 0) + (measure.cache_write_tokens or 0)
        fresh = None if measure.input_tokens is None else max(measure.input_tokens - cached, 0)
        m = measure.model
        quantities += [
            (f"{m}:input", fresh),
            (f"{m}:output", measure.output_tokens),  # includes reasoning tokens
            (f"{m}:cache_read", measure.cache_read_tokens),
            (f"{m}:cache_write", measure.cache_write_tokens),
        ]
    else:
        return None
    return prices.estimate(provider, quantities, at)


async def record_usage(
    session: AsyncSession,
    context: UsageContext,
    measure: UsageMeasure,
    prices: PriceBook,
    *,
    environment: str,
    occurred_at: datetime | None = None,
) -> LedgerResult:
    """Insert the usage event and cost entry. Flushes; the caller commits.

    A repeated `idempotency_key` is a no-op that returns the first event. The unique index on
    the hypertable includes `occurred_at`, so dedupe is by key alone, serialised with an
    advisory lock for the rest of the transaction.
    """
    key = context.idempotency_key or uuid.uuid4().hex
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"usage:{key}"))))
    existing = (
        await session.execute(
            select(UsageEvent.id).where(UsageEvent.idempotency_key == key).limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        entry_id = (
            await session.execute(
                select(CostEntry.id)
                .where(CostEntry.usage_event_id == existing, CostEntry.superseded_by_id.is_(None))
                .limit(1)
            )
        ).scalar_one_or_none()
        return LedgerResult(existing, entry_id, duplicate=True)

    when = occurred_at or datetime.now(UTC)
    event = UsageEvent(
        id=uuid.uuid4(),
        occurred_at=when,
        idempotency_key=key,
        user_id=context.user_id,
        session_id=context.session_id,
        cost_center=context.cost_center,
        component=context.component,
        provider=measure.provider,
        model=measure.model,
        environment=context.environment or environment,
        external_ref=measure.external_ref,
        connected_seconds=measure.connected_seconds,
        billable_units=measure.billable_units,
        billable_unit=measure.billable_unit,
        input_tokens=measure.input_tokens,
        output_tokens=measure.output_tokens,
        cache_read_tokens=measure.cache_read_tokens,
        cache_write_tokens=measure.cache_write_tokens,
        reasoning_tokens=measure.reasoning_tokens,
        sandbox_seconds=measure.sandbox_seconds,
        storage_bytes=measure.storage_bytes,
        raw=measure.raw,
    )
    session.add(event)

    entry: CostEntry | None = None
    if measure.reported_cost_usd is not None:
        usd = measure.reported_cost_usd.quantize(MICRO)
        entry = _entry(event, CostKind.PROVIDER, usd, usd, "usd", None)
    elif (estimate := estimate_measure(measure, prices, when)) is not None:
        entry = _entry(
            event,
            CostKind.ESTIMATED,
            estimate.usd,
            estimate.native_amount,
            estimate.native_unit,
            estimate.pricing_version_id,
        )
    else:
        log.warning("usage_unpriced", provider=measure.provider, model=measure.model)
    if entry is not None:
        session.add(entry)
    await session.flush()
    return LedgerResult(event.id, entry.id if entry else None)


def _entry(
    event: UsageEvent,
    kind: CostKind,
    usd: Decimal,
    native_amount: Decimal,
    native_unit: str,
    pricing_version_id: uuid.UUID | None,
) -> CostEntry:
    return CostEntry(
        id=uuid.uuid4(),
        usage_event_id=event.id,
        user_id=event.user_id,
        session_id=event.session_id,
        cost_center=event.cost_center,
        component=event.component,
        provider=event.provider,
        kind=kind,
        native_amount=native_amount,
        native_unit=native_unit,
        native_currency="USD" if native_unit == "usd" else None,
        usd_amount=usd,
        pricing_version_id=pricing_version_id,
    )


async def reconcile_cost(
    session: AsyncSession,
    usage_event_id: uuid.UUID,
    usd_amount: Decimal,
    *,
    native_amount: Decimal | None = None,
    native_unit: str = "usd",
) -> uuid.UUID:
    """Add a `reconciled` entry and mark the live estimated/provider entries as superseded.

    Idempotent for an unchanged amount: if the live entry is already reconciled at that amount
    its id is returned. Reports must sum only entries where `superseded_by_id IS NULL`.
    """
    usd = usd_amount.quantize(MICRO)
    live = (
        (
            await session.execute(
                select(CostEntry).where(
                    CostEntry.usage_event_id == usage_event_id, CostEntry.superseded_by_id.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for e in live:
        if e.kind is CostKind.RECONCILED and e.usd_amount == usd:
            return e.id
    event = (
        await session.execute(select(UsageEvent).where(UsageEvent.id == usage_event_id).limit(1))
    ).scalar_one()
    new = _entry(event, CostKind.RECONCILED, usd, native_amount or usd, native_unit, None)
    session.add(new)
    await session.flush()
    if live:
        await session.execute(
            update(CostEntry)
            .where(CostEntry.id.in_([e.id for e in live]))
            .values(superseded_by_id=new.id)
        )
    return new.id


class DbUsageRecorder:
    """Records each call in its own transaction, so the ledger row survives a caller rollback."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        *,
        environment: str | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._environment = environment

    async def record(
        self, context: UsageContext, measure: UsageMeasure, *, occurred_at: datetime | None = None
    ) -> None:
        from sg_core.settings import get_settings

        maker = self._sessionmaker or get_sessionmaker()
        env = self._environment or get_settings().environment.value
        async with maker() as session, session.begin():
            await record_usage(
                session,
                context,
                measure,
                await PriceBook.load(session),
                environment=env,
                occurred_at=occurred_at,
            )
