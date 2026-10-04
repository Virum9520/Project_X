"""Postgres `AccountabilityStore`. Every method is its own short transaction.

Claims and state changes are single conditional UPDATEs (or `FOR UPDATE SKIP LOCKED` for the
claim), so concurrent workers cannot dispatch the same occurrence twice. DB integration tests
live in `tests/test_accountability_db.py` behind `SG_DB_TESTS=1`.
"""

import uuid
from collections.abc import Collection
from datetime import date, datetime
from typing import Any, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_core.accountability.states import ACTIVE
from sg_core.models.accountability import (
    CallAttempt,
    CallOccurrence,
    CallSchedule,
    Commitment,
    PushSubscription,
)
from sg_core.models.enums import CallChannelKind, CallState, CommitmentStatus

T = TypeVar("T")


class DbAccountabilityStore:
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    async def _insert(self, row: T) -> T:
        async with self._maker() as s, s.begin():
            s.add(row)
            await s.flush()
            await s.refresh(row)
        return row

    async def save(self, *rows: Commitment | CallSchedule | PushSubscription) -> None:
        async with self._maker() as s, s.begin():
            for row in rows:
                await s.merge(row)

    # ── commitments ──
    async def add_commitment(
        self,
        *,
        user_id: uuid.UUID,
        description: str,
        due_at: datetime | None,
        concept_key: str | None,
        session_id: uuid.UUID | None = None,
    ) -> Commitment:
        return await self._insert(
            Commitment(
                user_id=user_id,
                session_id=session_id,
                description=description,
                due_at=due_at,
                concept_key=concept_key,
            )
        )

    async def get_commitment(
        self, commitment_id: uuid.UUID, user_id: uuid.UUID
    ) -> Commitment | None:
        async with self._maker() as s:
            return await s.scalar(
                select(Commitment).where(
                    Commitment.id == commitment_id, Commitment.user_id == user_id
                )
            )

    async def list_commitments(
        self, user_id: uuid.UUID, *, statuses: Collection[CommitmentStatus] | None = None
    ) -> list[Commitment]:
        stmt = select(Commitment).where(Commitment.user_id == user_id)
        if statuses is not None:
            stmt = stmt.where(Commitment.status.in_(list(statuses)))
        async with self._maker() as s:
            rows = await s.scalars(
                stmt.order_by(Commitment.due_at.asc().nulls_last(), Commitment.created_at)
            )
            return list(rows)

    # ── schedules ──
    async def add_schedule(self, schedule: CallSchedule) -> CallSchedule:
        return await self._insert(schedule)

    async def get_schedule(self, schedule_id: uuid.UUID) -> CallSchedule | None:
        async with self._maker() as s:
            return await s.get(CallSchedule, schedule_id)

    async def list_schedules(
        self, user_id: uuid.UUID | None = None, *, enabled_only: bool = False
    ) -> list[CallSchedule]:
        stmt = select(CallSchedule)
        if user_id is not None:
            stmt = stmt.where(CallSchedule.user_id == user_id)
        if enabled_only:
            stmt = stmt.where(CallSchedule.enabled.is_(True))
        async with self._maker() as s:
            return list(await s.scalars(stmt.order_by(CallSchedule.created_at)))

    async def delete_schedule(self, schedule_id: uuid.UUID) -> None:
        async with self._maker() as s, s.begin():
            row = await s.get(CallSchedule, schedule_id)
            if row is not None:
                await s.delete(row)

    # ── occurrences ──
    async def ensure_occurrence(
        self,
        *,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
        local_date: date,
        scheduled_for: datetime,
    ) -> tuple[CallOccurrence, bool]:
        async with self._maker() as s, s.begin():
            inserted = await s.scalar(
                pg_insert(CallOccurrence)
                .values(
                    schedule_id=schedule_id,
                    user_id=user_id,
                    local_date=local_date,
                    scheduled_for=scheduled_for,
                    state=CallState.SCHEDULED,
                    is_test=False,
                )
                .on_conflict_do_nothing(index_elements=["schedule_id", "local_date"])
                .returning(CallOccurrence.id)
            )
            row = await s.scalar(
                select(CallOccurrence)
                .where(
                    CallOccurrence.schedule_id == schedule_id,
                    CallOccurrence.local_date == local_date,
                )
                .execution_options(populate_existing=True)
            )
        assert row is not None
        return row, inserted is not None

    async def ensure_test_occurrence(
        self, *, request_id: str, user_id: uuid.UUID, scheduled_for: datetime
    ) -> tuple[CallOccurrence, bool]:
        async with self._maker() as s, s.begin():
            inserted = await s.scalar(
                pg_insert(CallOccurrence)
                .values(
                    user_id=user_id,
                    local_date=scheduled_for.date(),
                    scheduled_for=scheduled_for,
                    state=CallState.SCHEDULED,
                    is_test=True,
                    request_id=request_id,
                )
                .on_conflict_do_nothing(index_elements=["request_id"])
                .returning(CallOccurrence.id)
            )
            row = await s.scalar(
                select(CallOccurrence)
                .where(CallOccurrence.request_id == request_id)
                .execution_options(populate_existing=True)
            )
        assert row is not None
        return row, inserted is not None

    async def get_occurrence(self, occurrence_id: uuid.UUID) -> CallOccurrence | None:
        async with self._maker() as s:
            return await s.get(CallOccurrence, occurrence_id)

    async def claim_due(self, now: datetime, limit: int = 20) -> list[CallOccurrence]:
        async with self._maker() as s, s.begin():
            ids = list(
                await s.scalars(
                    select(CallOccurrence.id)
                    .where(
                        CallOccurrence.state == CallState.SCHEDULED,
                        CallOccurrence.scheduled_for <= now,
                    )
                    .order_by(CallOccurrence.scheduled_for)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            if not ids:
                return []
            await s.execute(
                update(CallOccurrence)
                .where(CallOccurrence.id.in_(ids))
                .values(state=CallState.QUEUED)
            )
            rows = await s.scalars(
                select(CallOccurrence)
                .where(CallOccurrence.id.in_(ids))
                .order_by(CallOccurrence.scheduled_for)
                .execution_options(populate_existing=True)
            )
            return list(rows)

    async def transition_occurrence(
        self, occurrence_id: uuid.UUID, expected: Collection[CallState], new: CallState
    ) -> bool:
        async with self._maker() as s, s.begin():
            result = await s.execute(
                update(CallOccurrence)
                .where(CallOccurrence.id == occurrence_id, CallOccurrence.state.in_(list(expected)))
                .values(state=new)
            )
        return bool(getattr(result, "rowcount", 0))

    async def occurrences_in_state(
        self, state: CallState, updated_before: datetime
    ) -> list[CallOccurrence]:
        async with self._maker() as s:
            rows = await s.scalars(
                select(CallOccurrence).where(
                    CallOccurrence.state == state, CallOccurrence.updated_at <= updated_before
                )
            )
            return list(rows)

    async def cancel_future_occurrences(self, schedule_id: uuid.UUID) -> int:
        async with self._maker() as s, s.begin():
            result = await s.execute(
                update(CallOccurrence)
                .where(
                    CallOccurrence.schedule_id == schedule_id,
                    CallOccurrence.state == CallState.SCHEDULED,
                )
                .values(state=CallState.CANCELLED)
            )
        return int(getattr(result, "rowcount", 0) or 0)

    # ── attempts ──
    async def add_attempt(
        self,
        *,
        occurrence_id: uuid.UUID,
        channel: CallChannelKind,
        previous_attempt_id: uuid.UUID | None = None,
    ) -> CallAttempt:
        async with self._maker() as s, s.begin():
            number = (
                await s.scalar(
                    select(func.coalesce(func.max(CallAttempt.attempt_no), 0)).where(
                        CallAttempt.occurrence_id == occurrence_id
                    )
                )
                or 0
            ) + 1
            row = CallAttempt(
                occurrence_id=occurrence_id,
                attempt_no=number,
                previous_attempt_id=previous_attempt_id,
                channel=channel,
                state=CallState.QUEUED,
            )
            s.add(row)
            await s.flush()
            await s.refresh(row)
        return row

    async def get_attempt(self, attempt_id: uuid.UUID) -> CallAttempt | None:
        async with self._maker() as s:
            return await s.get(CallAttempt, attempt_id)

    async def attempts_for_occurrence(self, occurrence_id: uuid.UUID) -> list[CallAttempt]:
        async with self._maker() as s:
            rows = await s.scalars(
                select(CallAttempt)
                .where(CallAttempt.occurrence_id == occurrence_id)
                .order_by(CallAttempt.attempt_no)
            )
            return list(rows)

    async def attempt_by_conversation(self, conversation_id: str) -> CallAttempt | None:
        async with self._maker() as s:
            return await s.scalar(
                select(CallAttempt).where(CallAttempt.el_conversation_id == conversation_id)
            )

    async def transition_attempt(
        self,
        attempt_id: uuid.UUID,
        expected: Collection[CallState],
        new: CallState,
        **fields: Any,
    ) -> bool:
        async with self._maker() as s, s.begin():
            result = await s.execute(
                update(CallAttempt)
                .where(CallAttempt.id == attempt_id, CallAttempt.state.in_(list(expected)))
                .values(state=new, **fields)
            )
        return bool(getattr(result, "rowcount", 0))

    async def update_attempt(self, attempt_id: uuid.UUID, **fields: Any) -> None:
        async with self._maker() as s, s.begin():
            await s.execute(
                update(CallAttempt).where(CallAttempt.id == attempt_id).values(**fields)
            )

    async def attempts_in_state(
        self, state: CallState, updated_before: datetime
    ) -> list[CallAttempt]:
        async with self._maker() as s:
            rows = await s.scalars(
                select(CallAttempt).where(
                    CallAttempt.state == state, CallAttempt.updated_at <= updated_before
                )
            )
            return list(rows)

    async def active_attempt_count(self) -> int:
        async with self._maker() as s:
            return int(
                await s.scalar(
                    select(func.count())
                    .select_from(CallAttempt)
                    .where(CallAttempt.state.in_(list(ACTIVE)))
                )
                or 0
            )

    async def ringing_attempt_for_user(self, user_id: uuid.UUID) -> CallAttempt | None:
        async with self._maker() as s:
            return await s.scalar(
                select(CallAttempt)
                .join(CallOccurrence, CallOccurrence.id == CallAttempt.occurrence_id)
                .where(CallOccurrence.user_id == user_id, CallAttempt.state == CallState.RINGING)
                .order_by(CallAttempt.created_at.desc())
                .limit(1)
            )

    # ── push ──
    async def upsert_push_subscription(
        self,
        *,
        user_id: uuid.UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
    ) -> PushSubscription:
        values = {
            "user_id": user_id,
            "endpoint": endpoint,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": user_agent,
        }
        async with self._maker() as s, s.begin():
            await s.execute(
                pg_insert(PushSubscription)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["endpoint"],
                    set_={
                        "user_id": user_id,
                        "p256dh": p256dh,
                        "auth": auth,
                        "user_agent": user_agent,
                        "revoked_at": None,
                    },
                )
            )
            row = await s.scalar(
                select(PushSubscription)
                .where(PushSubscription.endpoint == endpoint)
                .execution_options(populate_existing=True)
            )
        assert row is not None
        return row

    async def list_push_subscriptions(self, user_id: uuid.UUID) -> list[PushSubscription]:
        async with self._maker() as s:
            rows = await s.scalars(
                select(PushSubscription).where(
                    PushSubscription.user_id == user_id, PushSubscription.revoked_at.is_(None)
                )
            )
            return list(rows)

    async def revoke_push_subscription(self, endpoint: str) -> None:
        async with self._maker() as s, s.begin():
            await s.execute(
                update(PushSubscription)
                .where(PushSubscription.endpoint == endpoint)
                .values(revoked_at=func.now())
            )
