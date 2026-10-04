"""Bhima accountability: scheduling maths, scheduler, dispatcher state machine, channels,
commitments and retention. All in memory (no database)."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pytest

from sg_core.accountability import (
    AccountabilityStore,
    CallDispatcher,
    CallNotAcceptable,
    CommitmentRejected,
    DispatchPolicy,
    DispatchRequest,
    DueConcept,
    InMemoryAccountabilityStore,
    InMemoryBudgetGuard,
    InMemoryRetentionSource,
    PhoneCallChannel,
    PhoneCallHandle,
    PushError,
    PushGoneError,
    PushTarget,
    ScheduleRejected,
    ScheduleSpec,
    WebCallChannel,
    can_transition,
    create_schedule,
    delete_schedule,
    in_quiet_hours,
    log_commitment,
    materialize_occurrences,
    occurrence_instant,
    plan_occurrences,
    plan_retention,
    record_observed_completion,
    report_progress,
    retention_variables,
    set_enabled,
    update_schedule,
)
from sg_core.accountability.retention import choose_retention_concept
from sg_core.models.accountability import CallSchedule
from sg_core.models.enums import (
    CallChannelKind,
    CallState,
    CommitmentStatus,
    CompletionSource,
)

NY = "America/New_York"
POLICY = DispatchPolicy(consent_version="v1", ring_timeout=timedelta(seconds=45))
USER = uuid.uuid4()


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        self.now += timedelta(**kwargs)
        return self.now


class FakePush:
    def __init__(self, behaviour: dict[str, Exception] | None = None) -> None:
        self.sent: list[tuple[PushTarget, dict[str, Any]]] = []
        self.behaviour = behaviour or {}

    async def send(self, target: PushTarget, payload: dict[str, Any], ttl_seconds: int) -> None:
        if target.endpoint in self.behaviour:
            raise self.behaviour[target.endpoint]
        self.sent.append((target, payload))


class World:
    """A store, budget, web channel and dispatcher sharing one fake clock."""

    def __init__(self, now: datetime, push: FakePush | None = None, limit: str = "7.50") -> None:
        self.clock = Clock(now)
        self.store = InMemoryAccountabilityStore(clock=self.clock)
        self.budget = InMemoryBudgetGuard(Decimal(limit))
        self.push = push or FakePush()
        self.web = WebCallChannel(self.store, self.push, ring_timeout_seconds=45)
        self.dispatcher = CallDispatcher(
            self.store,
            self.budget,
            {CallChannelKind.WEB: self.web, CallChannelKind.PHONE: PhoneCallChannel()},
            POLICY,
        )

    async def schedule(self, **overrides: Any) -> CallSchedule:
        spec = ScheduleSpec(
            tz=overrides.pop("tz", NY),
            local_time=overrides.pop("local_time", time(18, 0)),
            days=overrides.pop("days", [1, 2, 3, 4, 5, 6, 7]),
            consent_ver=overrides.pop("consent_ver", "v1"),
            **overrides,
        )
        return await create_schedule(self.store, USER, spec, POLICY)

    async def due_occurrence(self, **overrides: Any) -> uuid.UUID:
        """A schedule whose call is due right now (18:00 New York = 22:00 UTC in October)."""
        await self.schedule(**overrides)
        assert await materialize_occurrences(self.store, self.clock.now) == 1
        return next(iter(self.store.occurrences))


def evening() -> datetime:
    return datetime(2026, 10, 5, 22, 0, tzinfo=UTC)  # Monday 18:00 in New York (EDT)


# ── scheduling maths ──
def test_dst_gap_is_skipped_and_fold_runs_once() -> None:
    assert occurrence_instant(date(2026, 3, 8), time(2, 30), NY) is None  # spring forward
    assert occurrence_instant(date(2026, 3, 8), time(3, 30), NY) == datetime(
        2026, 3, 8, 7, 30, tzinfo=UTC
    )
    # 01:30 happens twice on 2026-11-01; the first (EDT, UTC-4) is used.
    assert occurrence_instant(date(2026, 11, 1), time(1, 30), NY) == datetime(
        2026, 11, 1, 5, 30, tzinfo=UTC
    )


def test_plan_occurrences_respects_weekdays_and_window() -> None:
    now = evening() - timedelta(hours=1)
    planned = plan_occurrences(
        tz=NY, local_time=time(18, 0), days=[1], now=now, horizon=timedelta(hours=3)
    )
    assert [p.local_date for p in planned] == [date(2026, 10, 5)]
    assert (
        plan_occurrences(
            tz=NY, local_time=time(18, 0), days=[2], now=now, horizon=timedelta(hours=3)
        )
        == []
    )


def test_plan_skips_a_nonexistent_local_time() -> None:
    now = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
    assert (
        plan_occurrences(
            tz=NY, local_time=time(2, 30), days=[7], now=now, horizon=timedelta(hours=12)
        )
        == []
    )


def test_quiet_hours_wrap_midnight() -> None:
    start, end = time(21, 30), time(8, 0)
    assert in_quiet_hours(datetime(2026, 10, 6, 3, 0, tzinfo=UTC), NY, start, end)  # 23:00 local
    assert in_quiet_hours(datetime(2026, 10, 6, 10, 0, tzinfo=UTC), NY, start, end)  # 06:00 local
    assert not in_quiet_hours(datetime(2026, 10, 5, 22, 0, tzinfo=UTC), NY, start, end)  # 18:00


def test_state_machine_forbids_skipping_and_leaving_terminal() -> None:
    assert can_transition(CallState.QUEUED, CallState.DISPATCHING)
    assert not can_transition(CallState.QUEUED, CallState.CONNECTED)
    assert not can_transition(CallState.MISSED, CallState.RINGING)
    assert can_transition(CallState.UNKNOWN, CallState.COMPLETED)


# ── schedules and scheduler ──
async def test_schedule_validation() -> None:
    w = World(evening())
    with pytest.raises(ScheduleRejected) as exc:
        await w.schedule(consent_ver="old")
    assert exc.value.code == "consent_required"
    with pytest.raises(ScheduleRejected) as exc:
        await w.schedule(tz="Mars/Base")
    assert exc.value.code == "bad_timezone"
    with pytest.raises(ScheduleRejected) as exc:
        await w.schedule(local_time=time(23, 0))
    assert exc.value.code == "quiet_hours"
    with pytest.raises(ScheduleRejected) as exc:
        await w.schedule(channel=CallChannelKind.PHONE)
    assert exc.value.code == "channel_unavailable"
    with pytest.raises(ScheduleRejected) as exc:
        await w.schedule(days=[0, 9])
    assert exc.value.code == "bad_days"
    with pytest.raises(ScheduleRejected) as exc:
        await w.schedule(max_duration_seconds=900)
    assert exc.value.code == "bad_duration"


async def test_scheduler_is_idempotent_across_runs_and_workers() -> None:
    w = World(evening() - timedelta(minutes=5))
    await w.schedule()
    assert await materialize_occurrences(w.store, w.clock.now) == 1
    assert await materialize_occurrences(w.store, w.clock.now) == 0
    w.clock.advance(minutes=1)
    assert await materialize_occurrences(w.store, w.clock.now) == 0
    assert len(w.store.occurrences) == 1


async def test_editing_a_schedule_cancels_pending_occurrences_but_keeps_the_day() -> None:
    w = World(evening() - timedelta(minutes=5))
    schedule = await w.schedule()
    await materialize_occurrences(w.store, w.clock.now)
    spec = ScheduleSpec(tz=NY, local_time=time(18, 0), days=[1], consent_ver="v1")
    await update_schedule(w.store, USER, schedule.id, spec, POLICY)
    occ = next(iter(w.store.occurrences.values()))
    assert occ.state is CallState.CANCELLED
    # Re-planning does not duplicate or resurrect today's occurrence.
    assert await materialize_occurrences(w.store, w.clock.now) == 0
    w.clock.advance(minutes=6)
    assert (await w.dispatcher.run_once(w.clock.now))["ringing"] == 0


async def test_others_cannot_touch_a_schedule() -> None:
    w = World(evening())
    schedule = await w.schedule()
    other = uuid.uuid4()
    assert await set_enabled(w.store, other, schedule.id, False) is None
    assert not await delete_schedule(w.store, other, schedule.id)
    assert await delete_schedule(w.store, USER, schedule.id)
    assert not w.store.schedules


# ── dispatcher: happy path and guards ──
async def test_due_call_rings_through_the_web_channel() -> None:
    w = World(evening())
    await w.store.upsert_push_subscription(
        user_id=USER, endpoint="https://push/1", p256dh="k", auth="a", user_agent=None
    )
    occ_id = await w.due_occurrence()
    report = await w.dispatcher.run_once(w.clock.now)
    assert report["ringing"] == 1
    occ = w.store.occurrences[occ_id]
    (attempt,) = await w.store.attempts_for_occurrence(occ_id)
    assert occ.state is CallState.RINGING and attempt.state is CallState.RINGING
    assert attempt.channel is CallChannelKind.WEB and attempt.dispatched_at is not None
    assert occ_id in w.budget.holds  # budget held for the call
    ((target, payload),) = w.push.sent
    assert payload["title"] == "Incoming call from Bhima"
    assert payload["attempt_id"] == str(attempt.id)
    assert target.endpoint == "https://push/1"
    # Nothing else is due, so a second run does nothing.
    assert (await w.dispatcher.run_once(w.clock.now))["ringing"] == 0


async def test_ring_survives_push_failures() -> None:
    push = FakePush(
        {"https://push/gone": PushGoneError("410"), "https://push/bad": PushError("500")}
    )
    w = World(evening(), push)
    for endpoint in ("https://push/gone", "https://push/bad", "https://push/ok"):
        await w.store.upsert_push_subscription(
            user_id=USER, endpoint=endpoint, p256dh="k", auth="a", user_agent=None
        )
    await w.due_occurrence()
    assert (await w.dispatcher.run_once(w.clock.now))["ringing"] == 1
    assert [t.endpoint for t, _ in w.push.sent] == ["https://push/ok"]
    live = {s.endpoint for s in await w.store.list_push_subscriptions(USER)}
    assert live == {"https://push/bad", "https://push/ok"}  # the gone one is revoked


async def test_budget_exceeded_fails_the_call_without_ringing() -> None:
    w = World(evening(), limit="0.01")
    occ_id = await w.due_occurrence()
    report = await w.dispatcher.run_once(w.clock.now)
    assert report["budget_exceeded"] == 1
    assert w.store.occurrences[occ_id].state is CallState.FAILED
    (attempt,) = await w.store.attempts_for_occurrence(occ_id)
    assert attempt.error == "budget_exceeded"
    assert not w.push.sent and not w.budget.holds


@pytest.mark.parametrize(
    ("setup", "outcome"),
    [
        ("disable", "cancelled:schedule_disabled"),
        ("consent", "cancelled:consent_stale"),
        ("quiet", "cancelled:quiet_hours"),
    ],
)
async def test_recheck_cancels_and_releases_the_hold(setup: str, outcome: str) -> None:
    w = World(evening())
    occ_id = await w.due_occurrence()
    schedule = next(iter(w.store.schedules.values()))
    now = w.clock.now
    if setup == "disable":
        schedule.enabled = False
    elif setup == "consent":
        schedule.consent_ver = "older"
    else:  # the call is due, but the dispatcher only gets to it inside the quiet window
        now = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)  # 22:00 local
        w.dispatcher = CallDispatcher(
            w.store,
            w.budget,
            {CallChannelKind.WEB: w.web},
            DispatchPolicy(consent_version="v1", late_grace=timedelta(hours=12)),
        )
    report = await w.dispatcher.run_once(now)
    assert report[outcome] == 1
    assert w.store.occurrences[occ_id].state is CallState.CANCELLED
    assert not w.budget.holds and not w.push.sent
    assert await w.store.attempts_for_occurrence(occ_id) == []


async def test_deleted_schedule_cancels_in_flight_occurrence() -> None:
    w = World(evening())
    occ_id = await w.due_occurrence()
    w.store.schedules.clear()  # deleted after the occurrence was created
    report = await w.dispatcher.run_once(w.clock.now)
    assert report["cancelled:schedule_deleted"] == 1
    assert w.store.occurrences[occ_id].state is CallState.CANCELLED


async def test_late_occurrences_are_missed_not_called() -> None:
    w = World(evening())
    occ_id = await w.due_occurrence()
    w.clock.advance(minutes=45)  # worker was down past the grace window
    report = await w.dispatcher.run_once(w.clock.now)
    assert report["missed_late"] == 1
    assert w.store.occurrences[occ_id].state is CallState.MISSED
    assert not w.push.sent


async def test_no_slot_requeues_and_retry_reserves_once() -> None:
    w = World(evening())
    w.dispatcher = CallDispatcher(
        w.store,
        w.budget,
        {CallChannelKind.WEB: w.web},
        DispatchPolicy(consent_version="v1", max_concurrent=0),
    )
    occ_id = await w.due_occurrence()
    assert (await w.dispatcher.run_once(w.clock.now))["no_slot"] == 1
    assert w.store.occurrences[occ_id].state is CallState.SCHEDULED
    w.dispatcher = CallDispatcher(w.store, w.budget, {CallChannelKind.WEB: w.web}, POLICY)
    assert (await w.dispatcher.run_once(w.clock.now))["ringing"] == 1
    assert list(w.budget.holds) == [occ_id]


async def test_retried_dispatch_never_double_reserves() -> None:
    w = World(evening())
    occ_id = await w.due_occurrence()
    await w.budget.reserve(
        occurrence_id=occ_id,
        user_id=USER,
        is_test=False,
        amount_usd=Decimal("0.2"),
        ttl=timedelta(minutes=5),
    )  # a crashed earlier run already held budget for this occurrence
    await w.dispatcher.run_once(w.clock.now)
    assert w.budget.reserve_calls == 2 and len(w.budget.holds) == 1
    assert w.budget.committed() == Decimal("0.2")


async def test_channel_exception_fails_the_call() -> None:
    class Boom:
        kind = CallChannelKind.WEB

        async def dispatch(self, request: DispatchRequest) -> Any:
            raise RuntimeError("push service down")

        async def cancel(self, attempt_id: uuid.UUID) -> None: ...

    w = World(evening())
    w.dispatcher = CallDispatcher(w.store, w.budget, {CallChannelKind.WEB: Boom()}, POLICY)
    occ_id = await w.due_occurrence()
    report = await w.dispatcher.run_once(w.clock.now)
    assert report.outcomes["failed:channel_error: push service down"] == 1
    assert w.store.occurrences[occ_id].state is CallState.FAILED
    assert not w.budget.holds


async def test_concurrent_claims_dispatch_once() -> None:
    w = World(evening())
    await w.due_occurrence()
    first = await w.store.claim_due(w.clock.now)
    second = await w.store.claim_due(w.clock.now)
    assert len(first) == 1 and second == []


# ── accept, decline, timeout, completion ──
async def ringing(w: World) -> tuple[uuid.UUID, uuid.UUID]:
    occ_id = await w.due_occurrence()
    await w.dispatcher.run_once(w.clock.now)
    (attempt,) = await w.store.attempts_for_occurrence(occ_id)
    return occ_id, attempt.id


async def test_accept_connects_and_complete_settles_actual_cost() -> None:
    w = World(evening())
    occ_id, attempt_id = await ringing(w)
    w.clock.advance(seconds=10)
    attempt = await w.dispatcher.accept(attempt_id, USER, w.clock.now)
    assert attempt.state is CallState.CONNECTED
    assert w.store.occurrences[occ_id].state is CallState.CONNECTED
    w.clock.advance(seconds=60)
    assert await w.dispatcher.complete(attempt_id, now=w.clock.now)
    assert w.store.occurrences[occ_id].state is CallState.COMPLETED
    assert w.budget.settled[occ_id] == POLICY.estimate_usd(60)
    assert not w.budget.holds
    assert not await w.dispatcher.complete(attempt_id, now=w.clock.now)  # idempotent


async def test_accept_is_refused_for_other_users_late_taps_and_second_taps() -> None:
    w = World(evening())
    _, attempt_id = await ringing(w)
    with pytest.raises(CallNotAcceptable) as exc:
        await w.dispatcher.accept(attempt_id, uuid.uuid4(), w.clock.now)
    assert exc.value.reason == "not_found"
    with pytest.raises(CallNotAcceptable) as exc:
        await w.dispatcher.accept(attempt_id, USER, w.clock.now + timedelta(seconds=60))
    assert exc.value.reason == "expired"
    await w.dispatcher.accept(attempt_id, USER, w.clock.now)
    with pytest.raises(CallNotAcceptable) as exc:
        await w.dispatcher.accept(attempt_id, USER, w.clock.now)
    assert exc.value.reason == "not_ringing"


async def test_unanswered_call_times_out_to_missed_and_is_not_redialled() -> None:
    w = World(evening())
    occ_id, attempt_id = await ringing(w)
    w.clock.advance(seconds=30)
    assert (await w.dispatcher.sweep(w.clock.now)).outcomes["missed"] == 0  # still ringing
    w.clock.advance(seconds=30)
    assert (await w.dispatcher.sweep(w.clock.now)).outcomes["missed"] == 1
    assert w.store.occurrences[occ_id].state is CallState.MISSED
    assert w.store.attempts[attempt_id].error == "ring_timeout"
    assert not w.budget.holds and occ_id in w.budget.released
    # No auto-redial: more runs and sweeps never create another attempt or push.
    await w.dispatcher.run_once(w.clock.now)
    await w.dispatcher.sweep(w.clock.now)
    assert len(await w.store.attempts_for_occurrence(occ_id)) == 1
    assert len(w.push.sent) == 0 or len({p["attempt_id"] for _, p in w.push.sent}) == 1
    with pytest.raises(CallNotAcceptable):
        await w.dispatcher.accept(attempt_id, USER, w.clock.now)


async def test_decline_releases_the_hold() -> None:
    w = World(evening())
    occ_id, attempt_id = await ringing(w)
    assert not await w.dispatcher.decline(attempt_id, uuid.uuid4())
    assert await w.dispatcher.decline(attempt_id, USER, w.clock.now)
    assert w.store.occurrences[occ_id].state is CallState.CANCELLED
    assert not w.budget.holds


async def test_session_failure_after_accept_fails_the_call() -> None:
    w = World(evening())
    occ_id, attempt_id = await ringing(w)
    await w.dispatcher.accept(attempt_id, USER, w.clock.now)
    assert await w.dispatcher.fail_connected(attempt_id, "voice provider unavailable", w.clock.now)
    assert w.store.occurrences[occ_id].state is CallState.FAILED
    assert not w.budget.holds


async def test_connected_call_without_end_signal_becomes_unknown_then_completes() -> None:
    w = World(evening())
    occ_id, attempt_id = await ringing(w)
    await w.dispatcher.accept(attempt_id, USER, w.clock.now)
    w.clock.advance(minutes=4)
    assert (await w.dispatcher.sweep(w.clock.now)).outcomes["unknown"] == 1
    assert w.store.occurrences[occ_id].state is CallState.UNKNOWN
    assert occ_id in w.budget.settled  # likely spent: settled at the full estimate
    assert await w.dispatcher.complete(attempt_id, duration_seconds=80, now=w.clock.now)
    assert w.store.occurrences[occ_id].state is CallState.COMPLETED


async def test_interrupted_dispatch_is_recovered_not_redialled() -> None:
    w = World(evening())
    occ_id = await w.due_occurrence()
    await w.store.claim_due(w.clock.now)  # worker claimed it, then died
    w.clock.advance(minutes=6)
    assert (await w.dispatcher.sweep(w.clock.now)).outcomes["requeued"] == 1
    assert w.store.occurrences[occ_id].state is CallState.SCHEDULED
    # Past the late grace, the recovered occurrence is missed instead of ringing hours late.
    w.clock.advance(minutes=30)
    assert (await w.dispatcher.run_once(w.clock.now))["missed_late"] == 1


async def test_test_calls_dedupe_on_request_id_and_use_no_schedule() -> None:
    w = World(evening())
    first, created = await w.store.ensure_test_occurrence(
        request_id="req-1", user_id=USER, scheduled_for=w.clock.now
    )
    again, created_again = await w.store.ensure_test_occurrence(
        request_id="req-1", user_id=USER, scheduled_for=w.clock.now
    )
    assert created and not created_again and first.id == again.id
    assert (await w.dispatcher.run_once(w.clock.now))["ringing"] == 1


# ── phone stub ──
async def test_phone_channel_is_a_stub_without_a_relay() -> None:
    result = await PhoneCallChannel().dispatch(
        DispatchRequest(uuid.uuid4(), uuid.uuid4(), USER, 120, destination="+15555550100")
    )
    assert result.state is CallState.FAILED
    assert result.error == PhoneCallChannel.NOT_IMPLEMENTED


async def test_phone_channel_records_conversation_and_call_sid_when_a_relay_exists() -> None:
    class Relay:
        async def place_call(self, destination: str, max_duration_seconds: int) -> PhoneCallHandle:
            return PhoneCallHandle("conv_1", "CA123")

        async def hang_up(self, call_sid: str) -> None: ...

    result = await PhoneCallChannel(Relay()).dispatch(
        DispatchRequest(uuid.uuid4(), uuid.uuid4(), USER, 120, destination="+15555550100")
    )
    assert result.state is CallState.RINGING
    assert result.attempt_fields == {"el_conversation_id": "conv_1", "twilio_call_sid": "CA123"}


# ── commitments ──
async def commit(store: AccountabilityStore, now: datetime, **kw: Any) -> Any:
    args: dict[str, Any] = {
        "user_id": USER,
        "tz": NY,
        "description": "Solve two graph problems",
        "due_local": "2026-10-06T21:00",
        "confirmed_by_learner": True,
        "now": now,
    } | kw
    return await log_commitment(store, **args)


async def test_log_commitment_converts_local_time_and_requires_confirmation() -> None:
    store = InMemoryAccountabilityStore()
    now = evening()
    row, created = await commit(store, now)
    assert created and row.due_at == datetime(2026, 10, 7, 1, 0, tzinfo=UTC)  # 21:00 EDT
    assert row.status is CommitmentStatus.OPEN and row.completion_source is None
    with pytest.raises(CommitmentRejected) as exc:
        await commit(store, now, confirmed_by_learner=False)
    assert exc.value.code == "not_confirmed"
    for bad, code in [
        ("2026-10-01T09:00", "due_in_past"),
        ("2027-06-01T09:00", "due_too_far"),
        ("tomorrow", "bad_due"),
    ]:
        with pytest.raises(CommitmentRejected) as exc:
            await commit(store, now, due_local=bad)
        assert exc.value.code == code


async def test_log_commitment_is_idempotent_for_a_retried_tool_call() -> None:
    store = InMemoryAccountabilityStore()
    first, _ = await commit(store, evening())
    second, created = await commit(store, evening(), description="solve  two graph problems")
    assert not created and second.id == first.id
    assert len(store.commitments) == 1


async def test_self_report_stays_separate_from_observed_completion() -> None:
    store = InMemoryAccountabilityStore()
    now = evening()
    row, _ = await commit(store, now)
    done = await report_progress(
        store, user_id=USER, commitment_id=row.id, status="done", learner_words="did both", now=now
    )
    assert done is not None
    assert done.status is CommitmentStatus.COMPLETED
    assert done.completion_source is CompletionSource.SELF_REPORTED
    assert done.reported_status == "done" and done.reported_note == "did both"
    observed = await record_observed_completion(
        store, user_id=USER, commitment_id=row.id, now=now + timedelta(hours=1)
    )
    assert observed is not None and observed.completion_source is CompletionSource.OBSERVED
    # A later self-report never downgrades observed completion.
    again = await report_progress(
        store, user_id=USER, commitment_id=row.id, status="not_done", now=now
    )
    assert again is not None
    assert again.status is CommitmentStatus.COMPLETED
    assert again.completion_source is CompletionSource.OBSERVED


async def test_report_progress_outcomes_and_ownership() -> None:
    store = InMemoryAccountabilityStore()
    now = evening()
    partly, _ = await commit(store, now, description="Read chapter four")
    missed, _ = await commit(
        store, now, description="Write the report", due_local="2026-10-05T19:00"
    )
    change, _ = await commit(store, now, description="Run five miles")
    assert (
        await report_progress(
            store, user_id=USER, commitment_id=partly.id, status="partly_done", now=now
        )
    ).status is CommitmentStatus.OPEN  # type: ignore[union-attr]
    later = now + timedelta(days=2)
    assert (
        await report_progress(
            store, user_id=USER, commitment_id=missed.id, status="not_done", now=later
        )
    ).status is CommitmentStatus.MISSED  # type: ignore[union-attr]
    assert (
        await report_progress(
            store, user_id=USER, commitment_id=change.id, status="wants_to_change", now=now
        )
    ).status is CommitmentStatus.CANCELLED  # type: ignore[union-attr]
    assert (
        await report_progress(store, user_id=uuid.uuid4(), commitment_id=partly.id, status="done")
        is None
    )


def test_habit_completion_never_touches_evidence() -> None:
    import ast
    from pathlib import Path

    import sg_core.accountability.commitments as module

    tree = ast.parse(Path(module.__file__ or "").read_text())
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {m for m in imported if m.startswith(("sg_core.rules", "sg_core.memory"))}
    assert "sg_core.models.evidence" not in imported


# ── retention ──
def test_retention_prefers_wilting_then_overdue_and_skips_recent() -> None:
    due = [
        DueConcept("dsa.graphs", "Graphs", "due"),
        DueConcept("os.paging", "Paging", "wilting"),
        DueConcept("dsa.heaps", "Heaps", "due"),
    ]
    assert choose_retention_concept(due, set()).concept_key == "os.paging"  # type: ignore[union-attr]
    assert choose_retention_concept(due, {"os.paging"}).concept_key == "dsa.graphs"  # type: ignore[union-attr]
    assert choose_retention_concept(due, {c.key for c in due}) is None


async def test_plan_retention_asks_one_concept_and_avoids_repeats() -> None:
    source = InMemoryRetentionSource(
        [DueConcept("dsa.graphs", "Graphs"), DueConcept("dsa.heaps", "Heaps")]
    )
    now = evening()
    first = await plan_retention(source, USER, now)
    assert first is not None and first.concept_key == "dsa.graphs"
    await source.record_request(USER, first, uuid.uuid4())
    second = await plan_retention(source, USER, datetime.now(UTC))
    assert second is not None and second.concept_key == "dsa.heaps"
    assert first.dynamic_variables() == {
        "retention_concept": "dsa.graphs",
        "retention_concept_title": "Graphs",
    }
    assert retention_variables(None)["retention_concept"] == "none"
    assert await plan_retention(InMemoryRetentionSource(), USER, now) is None
