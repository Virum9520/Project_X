"""The minute tick against in-memory fakes: create, dispatch and sweep in one idempotent pass."""

import uuid
from datetime import UTC, datetime, time, timedelta

from sg_core.accountability import (
    CallDispatcher,
    DispatchPolicy,
    InMemoryAccountabilityStore,
    InMemoryBudgetGuard,
    ScheduleSpec,
    WebCallChannel,
    create_schedule,
)
from sg_core.models.enums import CallChannelKind, CallState
from sg_worker.accountability import run_tick

POLICY = DispatchPolicy(consent_version="v1", ring_timeout=timedelta(seconds=45))
USER = uuid.uuid4()


async def test_tick_creates_dispatches_and_times_out_without_duplicates() -> None:
    now = datetime(2026, 10, 5, 21, 59, tzinfo=UTC)  # a minute before 18:00 in New York
    store = InMemoryAccountabilityStore(clock=lambda: now)
    web = WebCallChannel(store, None, ring_timeout_seconds=45)
    dispatcher = CallDispatcher(store, InMemoryBudgetGuard(), {CallChannelKind.WEB: web}, POLICY)
    await create_schedule(
        store,
        USER,
        ScheduleSpec(tz="America/New_York", local_time=time(18, 0), days=[1], consent_ver="v1"),
        POLICY,
    )

    first = await run_tick(store, dispatcher, now)
    assert first.created == 1 and first.dispatched == {}  # planned, not yet due

    now += timedelta(minutes=1)
    second = await run_tick(store, dispatcher, now)
    assert second.created == 0 and second.dispatched == {"ringing": 1}
    (attempt,) = store.attempts.values()
    assert attempt.state is CallState.RINGING

    again = await run_tick(store, dispatcher, now)  # a retried or overlapping tick
    assert again.created == 0 and again.dispatched == {} and again.swept == {}

    now += timedelta(seconds=60)  # nobody answered
    third = await run_tick(store, dispatcher, now)
    assert third.swept == {"missed": 1}
    assert attempt.state is CallState.MISSED

    now += timedelta(minutes=10)  # still no redial
    last = await run_tick(store, dispatcher, now)
    assert last.created == 0 and last.dispatched == {}
    assert len(store.attempts) == 1
