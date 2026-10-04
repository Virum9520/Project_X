"""Accountability against a real database (schema at `alembic upgrade head`, migration 0002).

Opt-in with `SG_DB_TESTS=1`. Each test creates its own user and deletes it afterwards (cascades).
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.accountability import (
    BudgetExceededError,
    DbAccountabilityStore,
    DbBudgetGuard,
    DispatchPolicy,
    ScheduleSpec,
    create_schedule,
    log_commitment,
    materialize_occurrences,
    report_progress,
)
from sg_core.models.accountability import CallOccurrence
from sg_core.models.economics import BudgetReservation
from sg_core.models.enums import CallChannelKind, CallState, CommitmentStatus, ReservationStatus
from sg_core.models.identity import User
from sg_core.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

POLICY = DispatchPolicy(consent_version="v1")


@pytest.fixture
async def maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def user_id(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[uuid.UUID]:
    uid = uuid.uuid4()
    async with maker() as s, s.begin():
        s.add(
            User(
                id=uid,
                clerk_user_id=f"test_{uid.hex}",
                email=f"{uid.hex}@test.invalid",
                timezone="America/New_York",
            )
        )
    yield uid
    async with maker() as s, s.begin():
        await s.execute(delete(BudgetReservation).where(BudgetReservation.user_id == uid))
        await s.execute(delete(User).where(User.id == uid))


async def test_occurrence_key_is_unique_and_claims_do_not_overlap(
    maker: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> None:
    store = DbAccountabilityStore(maker)
    schedule = await create_schedule(
        store,
        user_id,
        ScheduleSpec(
            tz="America/New_York",
            local_time=time(18, 0),
            days=[1, 2, 3, 4, 5, 6, 7],
            consent_ver="v1",
        ),
        POLICY,
    )
    now = datetime.now(UTC)
    for _ in range(2):  # a repeated scheduler run is a no-op
        await materialize_occurrences(store, now, horizon=timedelta(days=1))
    async with maker() as s:
        count = await s.scalar(
            select(func.count()).where(CallOccurrence.schedule_id == schedule.id)
        )
    assert count is not None and 1 <= count <= 2

    due_at = now + timedelta(days=2)
    occ, created = await store.ensure_occurrence(
        schedule_id=schedule.id, user_id=user_id, local_date=date(2030, 1, 1), scheduled_for=due_at
    )
    again, created_again = await store.ensure_occurrence(
        schedule_id=schedule.id, user_id=user_id, local_date=date(2030, 1, 1), scheduled_for=due_at
    )
    assert created and not created_again and occ.id == again.id

    await store.transition_occurrence(occ.id, {CallState.SCHEDULED}, CallState.SCHEDULED)
    far = due_at + timedelta(days=1)
    first, second = await asyncio.gather(store.claim_due(far), store.claim_due(far))
    claimed = [o.id for o in (*first, *second) if o.id == occ.id]
    assert claimed == [occ.id]  # exactly one worker got it
    assert not await store.transition_occurrence(occ.id, {CallState.SCHEDULED}, CallState.QUEUED)


async def test_attempts_and_compare_and_set(
    maker: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> None:
    store = DbAccountabilityStore(maker)
    occ, _ = await store.ensure_test_occurrence(
        request_id=f"req-{uuid.uuid4()}", user_id=user_id, scheduled_for=datetime.now(UTC)
    )
    again, created = await store.ensure_test_occurrence(
        request_id=occ.request_id or "", user_id=user_id, scheduled_for=datetime.now(UTC)
    )
    assert not created and again.id == occ.id
    attempt = await store.add_attempt(occurrence_id=occ.id, channel=CallChannelKind.WEB)
    assert attempt.attempt_no == 1 and attempt.state is CallState.QUEUED
    assert await store.transition_attempt(
        attempt.id, {CallState.QUEUED}, CallState.RINGING, el_conversation_id="conv_x"
    )
    assert not await store.transition_attempt(attempt.id, {CallState.QUEUED}, CallState.FAILED)
    assert (await store.attempt_by_conversation("conv_x")) is not None
    assert (await store.ringing_attempt_for_user(user_id)) is not None
    assert await store.active_attempt_count() >= 1


async def test_commitments_keep_self_report_separate(
    maker: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> None:
    store = DbAccountabilityStore(maker)
    due = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    row, created = await log_commitment(
        store,
        user_id=user_id,
        tz="America/New_York",
        description="Solve two graph problems",
        due_local=due,
        confirmed_by_learner=True,
    )
    _, created_again = await log_commitment(
        store,
        user_id=user_id,
        tz="America/New_York",
        description="Solve two graph problems",
        due_local=due,
        confirmed_by_learner=True,
    )
    assert created and not created_again
    done = await report_progress(store, user_id=user_id, commitment_id=row.id, status="done")
    assert done is not None and done.status is CommitmentStatus.COMPLETED
    stored = await store.get_commitment(row.id, user_id)
    assert stored is not None
    assert (
        stored.completion_source is not None and stored.completion_source.value == "self_reported"
    )
    assert await store.get_commitment(row.id, uuid.uuid4()) is None


async def test_budget_guard_is_idempotent_per_occurrence_and_releases(
    maker: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> None:
    store = DbAccountabilityStore(maker)
    occ, _ = await store.ensure_test_occurrence(
        request_id=f"req-{uuid.uuid4()}", user_id=user_id, scheduled_for=datetime.now(UTC)
    )
    guard = DbBudgetGuard(maker, get_settings())
    for _ in range(2):  # a retried dispatch reserves once
        await guard.reserve(
            occurrence_id=occ.id,
            user_id=user_id,
            is_test=False,
            amount_usd=Decimal("0.24"),
            ttl=timedelta(minutes=10),
        )
    async with maker() as s:
        rows = list(
            await s.scalars(
                select(BudgetReservation).where(BudgetReservation.call_occurrence_id == occ.id)
            )
        )
    assert len(rows) == 1 and rows[0].status is ReservationStatus.RESERVED
    await guard.release(occ.id)
    async with maker() as s:
        row = await s.get(BudgetReservation, rows[0].id)
    assert row is not None and row.status is ReservationStatus.RELEASED

    with pytest.raises(BudgetExceededError):
        await guard.reserve(
            occurrence_id=occ.id,
            user_id=user_id,
            is_test=False,
            amount_usd=Decimal("9999"),
            ttl=timedelta(minutes=10),
        )
