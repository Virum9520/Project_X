"""`SqlAdminStore` against a real database (schema at `alembic upgrade head`).

Opt-in with `SG_DB_TESTS=1`. Every row is tagged with a unique value and removed afterwards, so
the tests are safe on a shared dev database; aggregates over other people's data are only
checked for shape.
"""

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from sg_api.admin.sql_store import SqlAdminStore
from sg_api.admin.store import CooldownError
from sg_core.economics.budget import BudgetExceededError
from sg_core.models.accountability import CallAttempt, CallOccurrence, CallSchedule
from sg_core.models.economics import BudgetReservation, CostEntry, UsageEvent
from sg_core.models.enums import (
    ActorType,
    CallChannelKind,
    CallState,
    Character,
    CostCenter,
    CostKind,
    ProviderEventStatus,
    ReservationStatus,
    SessionStatus,
)
from sg_core.models.identity import AuditLog, Profile, User
from sg_core.models.sessions import ProviderEvent
from sg_core.models.sessions import Session as VoiceSession
from sg_core.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

Maker = async_sessionmaker[AsyncSession]


@pytest.fixture
async def maker() -> AsyncIterator[Maker]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def store(maker: Maker) -> SqlAdminStore:
    return SqlAdminStore(maker, get_settings())


@dataclass
class Seed:
    tag: str
    user_id: uuid.UUID
    email: str
    occurrence_id: uuid.UUID
    event_id: uuid.UUID


@pytest.fixture
async def seed(maker: Maker) -> AsyncIterator[Seed]:
    tag = f"c21t{uuid.uuid4().hex[:10]}"
    email = f"{tag}@c21.test"
    now = datetime.now(UTC)
    user_id, event_a, event_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    schedule_id, occurrence_id = uuid.uuid4(), uuid.uuid4()
    async with maker() as s, s.begin():
        s.add(User(id=user_id, clerk_user_id=f"user_{tag}", email=email, display_name=tag))
        await s.flush()
        s.add(Profile(user_id=user_id, major="CS", onboarded_at=now))
        await s.flush()
        s.add_all(
            [
                VoiceSession(
                    user_id=user_id,
                    character=Character.DRONA,
                    mode="concept_exam",
                    status=SessionStatus.COMPLETED,
                    agent_version=tag,
                    duration_seconds=100,
                ),
                VoiceSession(
                    user_id=user_id,
                    character=Character.DRONA,
                    mode="concept_exam",
                    status=SessionStatus.FAILED,
                    is_test=True,
                ),
            ]
        )
        for event_id, model in ((event_a, f"model-{tag}"), (event_b, f"model-{tag}")):
            s.add(
                UsageEvent(
                    id=event_id,
                    idempotency_key=f"{tag}:{event_id}",
                    user_id=user_id,
                    cost_center=CostCenter.LEARNER,
                    component=tag,
                    provider="openrouter",
                    model=model,
                    environment="test",
                    connected_seconds=Decimal("30"),
                    input_tokens=100,
                    output_tokens=50,
                )
            )
        await s.flush()

        def entry(event: uuid.UUID, kind: CostKind, amount: str) -> CostEntry:
            return CostEntry(
                id=uuid.uuid4(),
                usage_event_id=event,
                user_id=user_id,
                cost_center=CostCenter.LEARNER,
                component=tag,
                provider="openrouter",
                kind=kind,
                native_amount=Decimal(amount),
                native_unit="usd",
                usd_amount=Decimal(amount),
            )

        live = entry(event_a, CostKind.ESTIMATED, "0.30")
        old = entry(event_b, CostKind.ESTIMATED, "0.20")
        reconciled = entry(event_b, CostKind.RECONCILED, "0.25")
        s.add_all([live, old, reconciled])
        await s.flush()
        old.superseded_by_id = reconciled.id  # the estimate must not be counted any more

        s.add(
            CallSchedule(
                id=schedule_id,
                user_id=user_id,
                channel=CallChannelKind.PHONE,
                destination="+15555550123",
                destination_verified_at=now,
                tz="America/Detroit",
                local_time=time(18, 30),
                days=[1, 3, 5],
                consent_ver="v1",
            )
        )
        await s.flush()
        s.add(
            CallOccurrence(
                id=occurrence_id,
                schedule_id=schedule_id,
                user_id=user_id,
                local_date=now.date(),
                scheduled_for=now + timedelta(hours=2),
                state=CallState.SCHEDULED,
            )
        )
        await s.flush()
        s.add(
            CallAttempt(
                occurrence_id=occurrence_id,
                attempt_no=1,
                channel=CallChannelKind.PHONE,
                state=CallState.QUEUED,
            )
        )
        s.add(
            ProviderEvent(
                provider=tag,
                event_id=tag,
                event_type="post_call_transcription",
                signature_verified=True,
                payload={},
                status=ProviderEventStatus.FAILED,
                attempts=3,
                error="boom " * 100,
            )
        )
        s.add(
            AuditLog(
                actor_type=ActorType.ADMIN,
                action=f"{tag}.action",
                target_type="call",
                target_id="1",
                before={"a": 1},
                after={"b": 2, "_meta": {"status_code": 200, "actor_email": "owner@c21.test"}},
            )
        )
    yield Seed(tag, user_id, email, occurrence_id, event_a)
    async with maker() as s, s.begin():
        await s.execute(delete(AuditLog).where(AuditLog.action == f"{tag}.action"))
        await s.execute(delete(ProviderEvent).where(ProviderEvent.provider == tag))
        await s.execute(delete(CostEntry).where(CostEntry.component == tag))
        await s.execute(delete(UsageEvent).where(UsageEvent.component == tag))
        await s.execute(delete(CallOccurrence).where(CallOccurrence.user_id == user_id))
        await s.execute(delete(CallSchedule).where(CallSchedule.user_id == user_id))
        await s.execute(delete(VoiceSession).where(VoiceSession.user_id == user_id))
        await s.execute(delete(Profile).where(Profile.user_id == user_id))
        await s.execute(delete(User).where(User.id == user_id))


# ── reads ──
async def test_costs_count_only_live_entries(store: SqlAdminStore, seed: Seed) -> None:
    now = datetime.now(UTC)
    report = await store.costs(now.date(), now.date(), "component", now)
    group = next(g for g in report.groups if g.key == seed.tag)
    # 0.30 estimated + 0.25 reconciled; the superseded 0.20 estimate is not counted
    assert group.usd == pytest.approx(0.55)
    assert group.entries == 2
    assert report.by_kind["reconciled"] >= 0.25
    assert report.usage.events >= 2
    assert report.usage.token_reporting_events >= 2
    assert any(d.day == now.date() for d in report.daily)


@pytest.mark.parametrize("group_by", ["provider", "cost_center", "model", "user", "component"])
async def test_every_cost_grouping_runs(store: SqlAdminStore, seed: Seed, group_by: str) -> None:
    now = datetime.now(UTC)
    report = await store.costs(now.date(), now.date(), group_by, now)  # type: ignore[arg-type]
    assert report.groups
    if group_by == "model":
        assert next(g for g in report.groups if g.key == f"model-{seed.tag}").usd == pytest.approx(
            0.55
        )
    if group_by == "user":
        mine = next(g for g in report.groups if g.key == str(seed.user_id))
        assert seed.tag not in mine.label  # masked
        assert mine.label.endswith("@c21.test")


async def test_user_search_and_detail(store: SqlAdminStore, seed: Seed) -> None:
    page = await store.list_users(seed.tag, 10, 0)
    assert page.total == 1
    row = page.items[0]
    assert row.id == str(seed.user_id)
    assert row.onboarded and row.sessions == 2
    assert row.spend_month_to_date_usd == pytest.approx(0.55)
    assert seed.email not in row.email_masked
    assert (await store.list_users("%", 10, 0)).total == 0  # wildcards are literal

    detail = await store.get_user(seed.user_id, datetime.now(UTC))
    assert detail is not None
    assert detail.sessions_total == 2
    assert detail.spend_by_component == {seed.tag: pytest.approx(0.55)}
    assert detail.budget.key.startswith(f"user:{seed.user_id}:")
    [schedule] = detail.schedules
    assert schedule.destination_masked == "********0123"
    assert schedule.destination_verified and schedule.days == [1, 3, 5]
    assert schedule.local_time == "18:30"
    assert len(detail.recent_sessions) == 2
    assert await store.get_user(uuid.uuid4(), datetime.now(UTC)) is None


async def test_calls_agents_overview_quality_audit(store: SqlAdminStore, seed: Seed) -> None:
    now = datetime.now(UTC)
    calls = await store.calls(now)
    mine = next(c for c in calls.upcoming if c.occurrence_id == str(seed.occurrence_id))
    assert mine.kind == "scheduled" and mine.state == "queued" and mine.attempt_no == 1
    assert mine.user_masked is not None and seed.tag not in mine.user_masked
    assert calls.state_counts_7d.get("scheduled", 0) >= 1

    agents = {a.character: a for a in await store.agents({"drona": "agent_x"}, now)}
    assert agents["drona"].configured and agents["drona"].agent_id == "agent_x"
    assert agents["drona"].sessions_30d >= 2 and agents["drona"].failed_30d >= 1
    assert seed.tag in agents["drona"].versions
    assert not agents["bhima"].configured

    overview = await store.overview(now)
    assert overview.active_users_30d >= 1
    assert overview.spend_month_to_date_usd >= 0.55
    assert overview.projected_month_end_usd >= 0
    assert overview.developer_budget is not None
    assert overview.freshness.usage_events_at is not None

    quality = await store.quality(now)
    failed = next(e for e in quality.failed_events if e.provider == seed.tag)
    assert failed.attempts == 3 and failed.error is not None and len(failed.error) <= 300
    assert quality.provider_events_by_status.get("failed", 0) >= 1
    assert quality.failed_sessions_7d >= 1

    page = await store.audit(action_prefix=seed.tag, actor_email=None, before=None, limit=10)
    [row] = page.items
    assert row.action == f"{seed.tag}.action"
    assert row.after == {"b": 2}  # internal _meta is lifted out, not leaked
    assert row.status_code == 200 and row.actor_email == "owner@c21.test"
    assert page.next_before is None


async def test_audit_paginates_newest_first(store: SqlAdminStore, maker: Maker) -> None:
    tag = f"c21p{uuid.uuid4().hex[:8]}"
    base = datetime.now(UTC) - timedelta(hours=1)
    async with maker() as s, s.begin():
        for i in range(3):
            s.add(
                AuditLog(
                    occurred_at=base + timedelta(minutes=i),
                    actor_type=ActorType.ADMIN,
                    action=f"{tag}.{i}",
                )
            )
    try:
        first = await store.audit(action_prefix=tag, actor_email=None, before=None, limit=2)
        assert [r.action for r in first.items] == [f"{tag}.2", f"{tag}.1"]
        assert first.next_before is not None
        second = await store.audit(
            action_prefix=tag, actor_email=None, before=first.next_before, limit=2
        )
        assert [r.action for r in second.items] == [f"{tag}.0"]
        assert second.next_before is None
    finally:
        async with maker() as s, s.begin():
            await s.execute(delete(AuditLog).where(AuditLog.action.like(f"{tag}.%")))


# ── Call now ──
async def _cleanup_call(maker: Maker, request_id: str) -> None:
    async with maker() as s, s.begin():
        occ = await s.scalar(
            select(CallOccurrence.id).where(CallOccurrence.request_id == request_id)
        )
        if occ is None:
            return
        await s.execute(
            delete(BudgetReservation).where(BudgetReservation.call_occurrence_id == occ)
        )
        await s.execute(delete(CallOccurrence).where(CallOccurrence.id == occ))


async def test_call_now_replay_budget_and_release(store: SqlAdminStore, maker: Maker) -> None:
    rid = f"c21-{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)
    try:
        record, created = await store.create_test_call(
            request_id=rid,
            channel=CallChannelKind.WEB,
            estimate_usd=Decimal("0.10"),
            budget_limit_usd=Decimal("1000000"),
            cooldown_s=0,
            now=now,
        )
        assert created and record.state is CallState.QUEUED
        async with maker() as s:
            occ = await s.get(CallOccurrence, record.occurrence_id)
            assert (
                occ is not None and occ.is_test and occ.schedule_id is None and occ.user_id is None
            )
            [hold] = (
                await s.scalars(
                    select(BudgetReservation).where(BudgetReservation.call_occurrence_id == occ.id)
                )
            ).all()
            assert hold.status is ReservationStatus.RESERVED
            assert hold.cost_center is CostCenter.DEVELOPER
            assert hold.reserved_usd == Decimal("0.100000")

        again, created_again = await store.create_test_call(
            request_id=rid,
            channel=CallChannelKind.WEB,
            estimate_usd=Decimal("0.10"),
            budget_limit_usd=Decimal("1000000"),
            cooldown_s=0,
            now=now,
        )
        assert not created_again and again.occurrence_id == record.occurrence_id
        async with maker() as s:
            holds = await s.scalar(
                select(func.count()).where(
                    BudgetReservation.call_occurrence_id == record.occurrence_id
                )
            )
            assert holds == 1  # a replay does not reserve again

        await store.record_dispatch(
            record,
            state=CallState.FAILED,
            el_conversation_id=None,
            twilio_call_sid=None,
            error="provider said no",
            release_budget=True,
        )
        async with maker() as s:
            attempt = await s.get(CallAttempt, record.attempt_id)
            assert attempt is not None and attempt.state is CallState.FAILED
            assert attempt.error == "provider said no" and attempt.dispatched_at is None
            hold = await s.scalar(
                select(BudgetReservation).where(
                    BudgetReservation.call_occurrence_id == record.occurrence_id
                )
            )
            assert hold is not None and hold.status is ReservationStatus.RELEASED
        replay = await store.create_test_call(
            request_id=rid,
            channel=CallChannelKind.WEB,
            estimate_usd=Decimal("0.10"),
            budget_limit_usd=Decimal("1000000"),
            cooldown_s=0,
            now=now,
        )
        assert replay[0].state is CallState.FAILED  # replays show the real outcome
    finally:
        await _cleanup_call(maker, rid)


async def test_call_now_cooldown_and_budget_write_nothing(
    store: SqlAdminStore, maker: Maker
) -> None:
    first_id, second_id, third_id = (f"c21-{uuid.uuid4().hex[:12]}" for _ in range(3))
    now = datetime.now(UTC)
    kwargs = {"channel": CallChannelKind.WEB, "now": now}
    try:
        await store.create_test_call(
            request_id=first_id,
            estimate_usd=Decimal("0.01"),
            budget_limit_usd=Decimal("1000000"),
            cooldown_s=0,
            **kwargs,  # type: ignore[arg-type]
        )
        with pytest.raises(CooldownError) as cooldown:
            await store.create_test_call(
                request_id=second_id,
                estimate_usd=Decimal("0.01"),
                budget_limit_usd=Decimal("1000000"),
                cooldown_s=3600,
                **kwargs,  # type: ignore[arg-type]
            )
        assert cooldown.value.retry_after_s > 0
        with pytest.raises(BudgetExceededError):
            await store.create_test_call(
                request_id=third_id,
                estimate_usd=Decimal("10"),
                budget_limit_usd=Decimal("0.0000001"),
                cooldown_s=0,
                **kwargs,  # type: ignore[arg-type]
            )
        async with maker() as s:
            n = await s.scalar(
                select(func.count()).where(CallOccurrence.request_id.in_([second_id, third_id]))
            )
            assert n == 0  # refused requests left no occurrence behind
    finally:
        for rid in (first_id, second_id, third_id):
            await _cleanup_call(maker, rid)
