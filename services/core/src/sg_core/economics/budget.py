"""Budget holds: reserve before spending, settle with the actual, release if unused.

Serialised per `budget_key` by a transaction-scoped advisory lock (there is no parent row to
`SELECT … FOR UPDATE`), so concurrent reservations cannot jointly exceed the limit. The lock is
held until the transaction ends: commit the reservation straight away. Spend counted against a
budget = settled reservations + unexpired live holds. Spend that bypasses a hold is invisible
here; route every metered call through one.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_core.db import get_sessionmaker
from sg_core.economics.pricing import MICRO
from sg_core.models.economics import BudgetReservation
from sg_core.models.enums import CostCenter, ReservationStatus
from sg_core.settings import Settings, get_settings

DEFAULT_HOLD_TTL = timedelta(minutes=30)


class BudgetExceededError(RuntimeError):
    def __init__(
        self, budget_key: str, limit_usd: Decimal, committed_usd: Decimal, requested_usd: Decimal
    ) -> None:
        super().__init__(
            f"budget {budget_key} exceeded: {committed_usd} committed + {requested_usd} "
            f"requested > {limit_usd} limit"
        )
        self.budget_key = budget_key
        self.limit_usd = limit_usd
        self.committed_usd = committed_usd
        self.requested_usd = requested_usd


class ReservationStateError(RuntimeError):
    """Settling a released reservation, or an unknown reservation id."""


def budget_key_for(
    cost_center: CostCenter, user_id: uuid.UUID | None = None, at: datetime | None = None
) -> str:
    """`user:<uuid>:2026-10`, `developer:2026-10` or `owner_assistant:2026-10` (UTC months)."""
    period = (at or datetime.now(UTC)).strftime("%Y-%m")
    if cost_center is CostCenter.LEARNER:
        if user_id is None:
            raise ValueError("learner budgets need a user_id")
        return f"user:{user_id}:{period}"
    if cost_center is CostCenter.INFRASTRUCTURE:
        raise ValueError("infrastructure cost is allocated, not budgeted per call")
    return f"{cost_center.value}:{period}"


def monthly_limit_usd(cost_center: CostCenter, settings: Settings | None = None) -> Decimal:
    s = settings or get_settings()
    limits = {
        CostCenter.LEARNER: s.learner_monthly_budget_usd,
        CostCenter.DEVELOPER: s.developer_monthly_budget_usd,
        CostCenter.OWNER_ASSISTANT: s.owner_assistant_monthly_budget_usd,
    }
    if cost_center not in limits:
        raise ValueError(f"no budget for cost center {cost_center.value}")
    return limits[cost_center]


async def _lock(session: AsyncSession, budget_key: str) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"budget:{budget_key}"))))


async def committed_usd(
    session: AsyncSession, budget_key: str, now: datetime | None = None
) -> Decimal:
    """Settled spend plus live (unexpired) holds."""
    now = now or datetime.now(UTC)
    settled = func.coalesce(func.sum(BudgetReservation.settled_usd), 0)
    held = func.coalesce(func.sum(BudgetReservation.reserved_usd), 0)
    base = select(settled).where(
        BudgetReservation.budget_key == budget_key,
        BudgetReservation.status == ReservationStatus.SETTLED,
    )
    live = select(held).where(
        BudgetReservation.budget_key == budget_key,
        BudgetReservation.status == ReservationStatus.RESERVED,
        BudgetReservation.expires_at > now,
    )
    return Decimal(await session.scalar(base) or 0) + Decimal(await session.scalar(live) or 0)


async def reserve(
    session: AsyncSession,
    *,
    budget_key: str,
    amount_usd: Decimal,
    limit_usd: Decimal,
    cost_center: CostCenter,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    call_occurrence_id: uuid.UUID | None = None,
    ttl: timedelta = DEFAULT_HOLD_TTL,
    now: datetime | None = None,
) -> BudgetReservation:
    """Hold `amount_usd`, or raise `BudgetExceededError`. Flushes; commit promptly."""
    amount = amount_usd.quantize(MICRO)
    if amount < 0:
        raise ValueError("amount_usd must not be negative")
    now = now or datetime.now(UTC)
    await _lock(session, budget_key)
    committed = await committed_usd(session, budget_key, now)
    if committed + amount > limit_usd:
        raise BudgetExceededError(budget_key, limit_usd, committed, amount)
    row = BudgetReservation(
        id=uuid.uuid4(),
        budget_key=budget_key,
        user_id=user_id,
        cost_center=cost_center,
        session_id=session_id,
        call_occurrence_id=call_occurrence_id,
        reserved_usd=amount,
        status=ReservationStatus.RESERVED,
        expires_at=now + ttl,
    )
    session.add(row)
    await session.flush()
    return row


async def _get_locked(session: AsyncSession, reservation_id: uuid.UUID) -> BudgetReservation:
    row = (
        await session.execute(
            select(BudgetReservation)
            .where(BudgetReservation.id == reservation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ReservationStateError(f"unknown reservation {reservation_id}")
    return row


async def settle(
    session: AsyncSession,
    reservation_id: uuid.UUID,
    actual_usd: Decimal,
    *,
    now: datetime | None = None,
) -> BudgetReservation:
    """Record what was actually spent. Idempotent: a settled hold keeps its first amount.

    Also valid on an expired hold (the money was spent). Actual may exceed the hold; the
    overage counts against the budget.
    """
    row = await _get_locked(session, reservation_id)
    if row.status is ReservationStatus.SETTLED:
        return row
    if row.status is ReservationStatus.RELEASED:
        raise ReservationStateError(f"reservation {reservation_id} was released")
    row.status = ReservationStatus.SETTLED
    row.settled_usd = actual_usd.quantize(MICRO)
    row.settled_at = now or datetime.now(UTC)
    await session.flush()
    return row


async def release(session: AsyncSession, reservation_id: uuid.UUID) -> BudgetReservation:
    """Give the hold back (the call never happened). No-op unless the hold is still live."""
    row = await _get_locked(session, reservation_id)
    if row.status is ReservationStatus.RESERVED:
        row.status = ReservationStatus.RELEASED
        row.settled_at = datetime.now(UTC)
        await session.flush()
    return row


async def expire_stale(session: AsyncSession, now: datetime | None = None) -> int:
    """Mark holds past `expires_at` as expired (they already stop counting). For a periodic job."""
    result = await session.execute(
        update(BudgetReservation)
        .where(
            BudgetReservation.status == ReservationStatus.RESERVED,
            BudgetReservation.expires_at <= (now or datetime.now(UTC)),
        )
        .values(status=ReservationStatus.EXPIRED)
    )
    return int(getattr(result, "rowcount", 0) or 0)


@dataclass(slots=True)
class Hold:
    reservation_id: uuid.UUID
    reserved_usd: Decimal
    # Set before leaving the block to settle at the real cost; defaults to the reserved amount.
    actual_usd: Decimal | None = None


@asynccontextmanager
async def budget_hold(
    *,
    budget_key: str,
    amount_usd: Decimal,
    limit_usd: Decimal,
    cost_center: CostCenter,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    call_occurrence_id: uuid.UUID | None = None,
    ttl: timedelta = DEFAULT_HOLD_TTL,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[Hold]:
    """Reserve, run the body, then settle (or release if the body raised before `actual_usd`).

    Each step is its own short transaction so the advisory lock is never held across the call.
    """
    maker = sessionmaker or get_sessionmaker()
    async with maker() as s, s.begin():
        row = await reserve(
            s,
            budget_key=budget_key,
            amount_usd=amount_usd,
            limit_usd=limit_usd,
            cost_center=cost_center,
            user_id=user_id,
            session_id=session_id,
            call_occurrence_id=call_occurrence_id,
            ttl=ttl,
        )
        hold = Hold(row.id, row.reserved_usd)
    try:
        yield hold
    except BaseException:
        async with maker() as s, s.begin():
            if hold.actual_usd is not None:
                await settle(s, hold.reservation_id, hold.actual_usd)
            else:
                await release(s, hold.reservation_id)
        raise
    async with maker() as s, s.begin():
        await settle(
            s,
            hold.reservation_id,
            hold.actual_usd if hold.actual_usd is not None else hold.reserved_usd,
        )
