"""Usage ledger and budget holds against a real database (schema at `alembic upgrade head`).

Opt-in with `SG_DB_TESTS=1`. Each test uses its own unique keys and cleans up what it commits.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.economics import (
    BudgetExceededError,
    PriceBook,
    ReservationStateError,
    UsageContext,
    UsageMeasure,
    budget_hold,
    committed_usd,
    expire_stale,
    reconcile_cost,
    record_usage,
    release,
    reserve,
    settle,
    sync_default_prices,
)
from sg_core.models.economics import BudgetReservation, CostEntry, UsageEvent
from sg_core.models.enums import CostCenter, CostKind, ReservationStatus
from sg_core.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)


@pytest.fixture
async def maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def key() -> str:
    return f"test:{uuid.uuid4()}"


async def _cleanup_budget(maker: async_sessionmaker[AsyncSession], budget_key: str) -> None:
    async with maker() as s, s.begin():
        await s.execute(delete(BudgetReservation).where(BudgetReservation.budget_key == budget_key))


def _ctx(idem: str) -> UsageContext:
    return UsageContext(cost_center=CostCenter.DEVELOPER, component="test", idempotency_key=idem)


# ── ledger ──
async def test_record_usage_is_idempotent_and_prices_the_call(
    maker: async_sessionmaker[AsyncSession], key: str
) -> None:
    measure = UsageMeasure(provider="e2b", sandbox_seconds=Decimal("10"))
    try:
        async with maker() as s, s.begin():
            first = await record_usage(s, _ctx(key), measure, PriceBook(), environment="test")
        async with maker() as s, s.begin():
            second = await record_usage(s, _ctx(key), measure, PriceBook(), environment="test")
            entry = await s.get(CostEntry, first.cost_entry_id)
            count = await s.scalar(select(func.count()).where(UsageEvent.idempotency_key == key))
        assert not first.duplicate and second.duplicate
        assert second.usage_event_id == first.usage_event_id
        assert count == 1
        assert entry is not None
        assert (entry.kind, entry.usd_amount) == (CostKind.ESTIMATED, Decimal("0.000140"))
    finally:
        async with maker() as s, s.begin():
            await s.execute(
                delete(CostEntry).where(
                    CostEntry.component == "test",
                    CostEntry.provider == "e2b",
                    CostEntry.cost_center == CostCenter.DEVELOPER,
                    CostEntry.usage_event_id.in_(
                        select(UsageEvent.id).where(UsageEvent.idempotency_key == key)
                    ),
                )
            )
            await s.execute(delete(UsageEvent).where(UsageEvent.idempotency_key == key))


async def test_provider_cost_wins_then_reconciliation_supersedes(
    maker: async_sessionmaker[AsyncSession], key: str
) -> None:
    measure = UsageMeasure(
        provider="openrouter",
        model="anthropic/claude-sonnet-4.5",
        input_tokens=10,
        output_tokens=10,
        reported_cost_usd=Decimal("0.0005"),
    )
    async with maker() as s, s.begin():
        res = await record_usage(s, _ctx(key), measure, PriceBook(), environment="test")
        provider_entry = await s.get(CostEntry, res.cost_entry_id)
        assert provider_entry is not None and provider_entry.kind is CostKind.PROVIDER
        new_id = await reconcile_cost(s, res.usage_event_id, Decimal("0.0006"))
        assert await reconcile_cost(s, res.usage_event_id, Decimal("0.0006")) == new_id
        live = (
            await s.scalars(
                select(CostEntry).where(
                    CostEntry.usage_event_id == res.usage_event_id,
                    CostEntry.superseded_by_id.is_(None),
                )
            )
        ).all()
        assert [(e.kind, e.usd_amount) for e in live] == [(CostKind.RECONCILED, Decimal("0.0006"))]
        await s.refresh(provider_entry)
        assert provider_entry.superseded_by_id == new_id
        await s.rollback()


async def test_unpriced_usage_records_event_without_cost(
    maker: async_sessionmaker[AsyncSession], key: str
) -> None:
    measure = UsageMeasure(provider="openrouter", model="nobody/model", input_tokens=5)
    async with maker() as s, s.begin():
        res = await record_usage(s, _ctx(key), measure, PriceBook(), environment="test")
        assert res.cost_entry_id is None
        await s.rollback()


async def test_sync_default_prices_is_idempotent(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as s, s.begin():
        await sync_default_prices(s)
        assert await sync_default_prices(s) == 0
        book = await PriceBook.load(s)
        entry = book.price("e2b", "sandbox_second")
        assert entry is not None and entry.id is not None
        await s.rollback()


# ── budget holds ──
async def test_reserve_settle_release_accounting(
    maker: async_sessionmaker[AsyncSession], key: str
) -> None:
    limit = Decimal("1.00")
    try:
        async with maker() as s, s.begin():
            a = await reserve(
                s,
                budget_key=key,
                amount_usd=Decimal("0.60"),
                limit_usd=limit,
                cost_center=CostCenter.DEVELOPER,
            )
        async with maker() as s, s.begin():
            with pytest.raises(BudgetExceededError):
                await reserve(
                    s,
                    budget_key=key,
                    amount_usd=Decimal("0.50"),
                    limit_usd=limit,
                    cost_center=CostCenter.DEVELOPER,
                )
        async with maker() as s, s.begin():
            await settle(s, a.id, Decimal("0.20"))  # the real cost was lower
            b = await reserve(
                s,
                budget_key=key,
                amount_usd=Decimal("0.80"),
                limit_usd=limit,
                cost_center=CostCenter.DEVELOPER,
            )
        async with maker() as s, s.begin():
            assert await committed_usd(s, key) == Decimal("1.0")
            await release(s, b.id)
            assert await committed_usd(s, key) == Decimal("0.2")
            # settle is idempotent: the first amount stands
            assert (await settle(s, a.id, Decimal("0.90"))).settled_usd == Decimal("0.200000")
            with pytest.raises(ReservationStateError):
                await settle(s, b.id, Decimal("0.1"))
    finally:
        await _cleanup_budget(maker, key)


async def test_expired_holds_stop_counting_but_can_still_settle(
    maker: async_sessionmaker[AsyncSession], key: str
) -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    try:
        async with maker() as s, s.begin():
            old = await reserve(
                s,
                budget_key=key,
                amount_usd=Decimal("0.90"),
                limit_usd=Decimal("1"),
                cost_center=CostCenter.DEVELOPER,
                now=past,
            )
        async with maker() as s, s.begin():
            assert await committed_usd(s, key) == 0
            await reserve(
                s,
                budget_key=key,
                amount_usd=Decimal("0.90"),
                limit_usd=Decimal("1"),
                cost_center=CostCenter.DEVELOPER,
            )
            assert await expire_stale(s) >= 1
            assert (await settle(s, old.id, Decimal("0.05"))).status is ReservationStatus.SETTLED
    finally:
        await _cleanup_budget(maker, key)


async def test_concurrent_reservations_never_exceed_the_limit(
    maker: async_sessionmaker[AsyncSession], key: str
) -> None:
    async def attempt() -> bool:
        try:
            async with maker() as s, s.begin():
                await reserve(
                    s,
                    budget_key=key,
                    amount_usd=Decimal("0.30"),
                    limit_usd=Decimal("1.00"),
                    cost_center=CostCenter.DEVELOPER,
                )
            return True
        except BudgetExceededError:
            return False

    try:
        results = await asyncio.gather(*(attempt() for _ in range(8)))
        assert sum(results) == 3  # 3 x 0.30 fits in 1.00; the 4th would not
        async with maker() as s:
            assert await committed_usd(s, key) == Decimal("0.9")
    finally:
        await _cleanup_budget(maker, key)


async def test_budget_hold_context_settles_and_releases(
    maker: async_sessionmaker[AsyncSession], key: str
) -> None:
    kwargs = {
        "budget_key": key,
        "limit_usd": Decimal("1"),
        "cost_center": CostCenter.DEVELOPER,
        "sessionmaker": maker,
    }
    try:
        async with budget_hold(amount_usd=Decimal("0.40"), **kwargs) as hold:  # type: ignore[arg-type]
            hold.actual_usd = Decimal("0.25")
        with pytest.raises(RuntimeError):
            async with budget_hold(amount_usd=Decimal("0.40"), **kwargs):  # type: ignore[arg-type]
                raise RuntimeError("provider failed")
        async with maker() as s:
            assert await committed_usd(s, key) == Decimal("0.25")
    finally:
        await _cleanup_budget(maker, key)
