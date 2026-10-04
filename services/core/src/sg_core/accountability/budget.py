"""Budget holds for calls, keyed by occurrence so a retried dispatch never double-reserves.

C03's `reserve` carries no idempotency key (see docs/PROGRESS.md), so the dispatcher guards
retries here: `reserve` first looks for a live or settled hold already tied to the occurrence.
Learner calls draw on the learner's monthly budget; call-now test calls on the developer budget.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_core.economics.budget import (
    BudgetExceededError,
    budget_key_for,
    monthly_limit_usd,
    release,
    reserve,
    settle,
)
from sg_core.models.economics import BudgetReservation
from sg_core.models.enums import CostCenter, ReservationStatus
from sg_core.settings import Settings

__all__ = ["BudgetExceededError", "BudgetGuard", "DbBudgetGuard", "InMemoryBudgetGuard"]


class BudgetGuard(Protocol):
    async def reserve(
        self,
        *,
        occurrence_id: uuid.UUID,
        user_id: uuid.UUID,
        is_test: bool,
        amount_usd: Decimal,
        ttl: timedelta,
    ) -> None:
        """Hold `amount_usd` for the occurrence (idempotent) or raise `BudgetExceededError`."""
        ...

    async def settle(self, occurrence_id: uuid.UUID, actual_usd: Decimal) -> None: ...

    async def release(self, occurrence_id: uuid.UUID) -> None: ...


class InMemoryBudgetGuard:
    def __init__(self, limit_usd: Decimal = Decimal("7.50")) -> None:
        self.limit_usd = limit_usd
        self.holds: dict[uuid.UUID, Decimal] = {}
        self.settled: dict[uuid.UUID, Decimal] = {}
        self.released: set[uuid.UUID] = set()
        self.reserve_calls = 0

    def committed(self) -> Decimal:
        return sum(self.holds.values(), Decimal(0)) + sum(self.settled.values(), Decimal(0))

    async def reserve(
        self,
        *,
        occurrence_id: uuid.UUID,
        user_id: uuid.UUID,
        is_test: bool,
        amount_usd: Decimal,
        ttl: timedelta,
    ) -> None:
        self.reserve_calls += 1
        if occurrence_id in self.holds or occurrence_id in self.settled:
            return
        if self.committed() + amount_usd > self.limit_usd:
            raise BudgetExceededError("memory", self.limit_usd, self.committed(), amount_usd)
        self.released.discard(occurrence_id)
        self.holds[occurrence_id] = amount_usd

    async def settle(self, occurrence_id: uuid.UUID, actual_usd: Decimal) -> None:
        if occurrence_id in self.holds:
            del self.holds[occurrence_id]
            self.settled[occurrence_id] = actual_usd

    async def release(self, occurrence_id: uuid.UUID) -> None:
        if self.holds.pop(occurrence_id, None) is not None:
            self.released.add(occurrence_id)


class DbBudgetGuard:
    def __init__(self, maker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._maker = maker
        self._settings = settings

    async def _existing(
        self, s: AsyncSession, occurrence_id: uuid.UUID
    ) -> BudgetReservation | None:
        return await s.scalar(
            select(BudgetReservation)
            .where(
                BudgetReservation.call_occurrence_id == occurrence_id,
                BudgetReservation.status.in_(
                    [ReservationStatus.RESERVED, ReservationStatus.SETTLED]
                ),
            )
            .order_by(BudgetReservation.created_at.desc())
            .limit(1)
        )

    async def reserve(
        self,
        *,
        occurrence_id: uuid.UUID,
        user_id: uuid.UUID,
        is_test: bool,
        amount_usd: Decimal,
        ttl: timedelta,
    ) -> None:
        center = CostCenter.DEVELOPER if is_test else CostCenter.LEARNER
        now = datetime.now(UTC)
        async with self._maker() as s, s.begin():
            if await self._existing(s, occurrence_id) is not None:
                return
            await reserve(
                s,
                budget_key=budget_key_for(center, None if is_test else user_id, now),
                amount_usd=amount_usd,
                limit_usd=monthly_limit_usd(center, self._settings),
                cost_center=center,
                user_id=user_id,
                call_occurrence_id=occurrence_id,
                ttl=ttl,
                now=now,
            )

    async def settle(self, occurrence_id: uuid.UUID, actual_usd: Decimal) -> None:
        async with self._maker() as s, s.begin():
            row = await self._existing(s, occurrence_id)
            if row is not None:
                await settle(s, row.id, actual_usd)

    async def release(self, occurrence_id: uuid.UUID) -> None:
        async with self._maker() as s, s.begin():
            row = await self._existing(s, occurrence_id)
            if row is not None and row.status is ReservationStatus.RESERVED:
                await release(s, row.id)
