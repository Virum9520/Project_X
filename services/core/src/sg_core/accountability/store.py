"""Persistence seam for accountability. `AccountabilityStore` is what the services use.

`InMemoryAccountabilityStore` backs unit tests and no-database runs; `DbAccountabilityStore`
(`db_store.py`) is the Postgres implementation. Both hand out the ORM models themselves (transient
instances in memory), so services read and mutate the same shapes either way; persist changes
with `save()`. State changes that race (claiming, ringing, accepting) go through the
compare-and-set methods, never through `save()`.
"""

import uuid
from collections.abc import Callable, Collection
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sg_core.accountability.states import ACTIVE
from sg_core.models.accountability import (
    CallAttempt,
    CallOccurrence,
    CallSchedule,
    Commitment,
    PushSubscription,
)
from sg_core.models.enums import CallChannelKind, CallState, CommitmentStatus


class AccountabilityStore(Protocol):
    async def save(self, *rows: Commitment | CallSchedule | PushSubscription) -> None: ...

    # commitments
    async def add_commitment(
        self,
        *,
        user_id: uuid.UUID,
        description: str,
        due_at: datetime | None,
        concept_key: str | None,
        session_id: uuid.UUID | None = None,
    ) -> Commitment: ...
    async def get_commitment(
        self, commitment_id: uuid.UUID, user_id: uuid.UUID
    ) -> Commitment | None: ...
    async def list_commitments(
        self, user_id: uuid.UUID, *, statuses: Collection[CommitmentStatus] | None = None
    ) -> list[Commitment]: ...

    # schedules
    async def add_schedule(self, schedule: CallSchedule) -> CallSchedule: ...
    async def get_schedule(self, schedule_id: uuid.UUID) -> CallSchedule | None: ...
    async def list_schedules(
        self, user_id: uuid.UUID | None = None, *, enabled_only: bool = False
    ) -> list[CallSchedule]: ...
    async def delete_schedule(self, schedule_id: uuid.UUID) -> None: ...

    # occurrences
    async def ensure_occurrence(
        self,
        *,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
        local_date: date,
        scheduled_for: datetime,
    ) -> tuple[CallOccurrence, bool]: ...
    async def ensure_test_occurrence(
        self, *, request_id: str, user_id: uuid.UUID, scheduled_for: datetime
    ) -> tuple[CallOccurrence, bool]: ...
    async def get_occurrence(self, occurrence_id: uuid.UUID) -> CallOccurrence | None: ...
    async def claim_due(self, now: datetime, limit: int = 20) -> list[CallOccurrence]: ...
    async def transition_occurrence(
        self, occurrence_id: uuid.UUID, expected: Collection[CallState], new: CallState
    ) -> bool: ...
    async def occurrences_in_state(
        self, state: CallState, updated_before: datetime
    ) -> list[CallOccurrence]: ...
    async def cancel_future_occurrences(self, schedule_id: uuid.UUID) -> int: ...

    # attempts
    async def add_attempt(
        self,
        *,
        occurrence_id: uuid.UUID,
        channel: CallChannelKind,
        previous_attempt_id: uuid.UUID | None = None,
    ) -> CallAttempt: ...
    async def get_attempt(self, attempt_id: uuid.UUID) -> CallAttempt | None: ...
    async def attempts_for_occurrence(self, occurrence_id: uuid.UUID) -> list[CallAttempt]: ...
    async def attempt_by_conversation(self, conversation_id: str) -> CallAttempt | None: ...
    async def transition_attempt(
        self,
        attempt_id: uuid.UUID,
        expected: Collection[CallState],
        new: CallState,
        **fields: Any,
    ) -> bool: ...
    async def update_attempt(self, attempt_id: uuid.UUID, **fields: Any) -> None: ...
    async def attempts_in_state(
        self, state: CallState, updated_before: datetime
    ) -> list[CallAttempt]: ...
    async def active_attempt_count(self) -> int: ...
    async def ringing_attempt_for_user(self, user_id: uuid.UUID) -> CallAttempt | None: ...

    # push subscriptions
    async def upsert_push_subscription(
        self,
        *,
        user_id: uuid.UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
    ) -> PushSubscription: ...
    async def list_push_subscriptions(self, user_id: uuid.UUID) -> list[PushSubscription]: ...
    async def revoke_push_subscription(self, endpoint: str) -> None: ...


class InMemoryAccountabilityStore:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))
        self.commitments: dict[uuid.UUID, Commitment] = {}
        self.schedules: dict[uuid.UUID, CallSchedule] = {}
        self.occurrences: dict[uuid.UUID, CallOccurrence] = {}
        self.attempts: dict[uuid.UUID, CallAttempt] = {}
        self.push: dict[str, PushSubscription] = {}

    # ── helpers ──
    def _now(self) -> datetime:
        return self.clock()

    async def save(self, *rows: Commitment | CallSchedule | PushSubscription) -> None:
        for row in rows:
            if isinstance(row, Commitment):
                row.updated_at = self._now()
                self.commitments[row.id] = row
            elif isinstance(row, CallSchedule):
                row.updated_at = self._now()
                self.schedules[row.id] = row
            else:
                self.push[row.endpoint] = row

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
        now = self._now()
        row = Commitment(
            id=uuid.uuid4(),
            user_id=user_id,
            session_id=session_id,
            description=description,
            due_at=due_at,
            status=CommitmentStatus.OPEN,
            concept_key=concept_key,
            created_at=now,
            updated_at=now,
        )
        self.commitments[row.id] = row
        return row

    async def get_commitment(
        self, commitment_id: uuid.UUID, user_id: uuid.UUID
    ) -> Commitment | None:
        row = self.commitments.get(commitment_id)
        return row if row is not None and row.user_id == user_id else None

    async def list_commitments(
        self, user_id: uuid.UUID, *, statuses: Collection[CommitmentStatus] | None = None
    ) -> list[Commitment]:
        rows = [
            c
            for c in self.commitments.values()
            if c.user_id == user_id and (statuses is None or c.status in statuses)
        ]
        far = datetime.max.replace(tzinfo=UTC)
        return sorted(rows, key=lambda c: (c.due_at or far, c.created_at))

    # ── schedules ──
    async def add_schedule(self, schedule: CallSchedule) -> CallSchedule:
        now = self._now()
        schedule.id = schedule.id or uuid.uuid4()
        schedule.created_at = now
        schedule.updated_at = now
        if schedule.enabled is None:
            schedule.enabled = True
        self.schedules[schedule.id] = schedule
        return schedule

    async def get_schedule(self, schedule_id: uuid.UUID) -> CallSchedule | None:
        return self.schedules.get(schedule_id)

    async def list_schedules(
        self, user_id: uuid.UUID | None = None, *, enabled_only: bool = False
    ) -> list[CallSchedule]:
        return [
            s
            for s in self.schedules.values()
            if (user_id is None or s.user_id == user_id) and (s.enabled or not enabled_only)
        ]

    async def delete_schedule(self, schedule_id: uuid.UUID) -> None:
        self.schedules.pop(schedule_id, None)
        for occ in list(self.occurrences.values()):
            if occ.schedule_id == schedule_id:
                del self.occurrences[occ.id]  # cascades, like the foreign key

    # ── occurrences ──
    def _new_occurrence(
        self,
        *,
        schedule_id: uuid.UUID | None,
        user_id: uuid.UUID,
        local_date: date,
        scheduled_for: datetime,
        is_test: bool,
        request_id: str | None,
    ) -> CallOccurrence:
        now = self._now()
        row = CallOccurrence(
            id=uuid.uuid4(),
            schedule_id=schedule_id,
            user_id=user_id,
            local_date=local_date,
            scheduled_for=scheduled_for,
            state=CallState.SCHEDULED,
            is_test=is_test,
            request_id=request_id,
            created_at=now,
            updated_at=now,
        )
        self.occurrences[row.id] = row
        return row

    async def ensure_occurrence(
        self,
        *,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
        local_date: date,
        scheduled_for: datetime,
    ) -> tuple[CallOccurrence, bool]:
        for occ in self.occurrences.values():
            if occ.schedule_id == schedule_id and occ.local_date == local_date:
                return occ, False
        row = self._new_occurrence(
            schedule_id=schedule_id,
            user_id=user_id,
            local_date=local_date,
            scheduled_for=scheduled_for,
            is_test=False,
            request_id=None,
        )
        return row, True

    async def ensure_test_occurrence(
        self, *, request_id: str, user_id: uuid.UUID, scheduled_for: datetime
    ) -> tuple[CallOccurrence, bool]:
        for occ in self.occurrences.values():
            if occ.request_id == request_id:
                return occ, False
        row = self._new_occurrence(
            schedule_id=None,
            user_id=user_id,
            local_date=scheduled_for.date(),
            scheduled_for=scheduled_for,
            is_test=True,
            request_id=request_id,
        )
        return row, True

    async def get_occurrence(self, occurrence_id: uuid.UUID) -> CallOccurrence | None:
        return self.occurrences.get(occurrence_id)

    async def claim_due(self, now: datetime, limit: int = 20) -> list[CallOccurrence]:
        due = sorted(
            (
                o
                for o in self.occurrences.values()
                if o.state is CallState.SCHEDULED and o.scheduled_for <= now
            ),
            key=lambda o: o.scheduled_for,
        )[:limit]
        for occ in due:
            occ.state = CallState.QUEUED
            occ.updated_at = self._now()
        return due

    async def transition_occurrence(
        self, occurrence_id: uuid.UUID, expected: Collection[CallState], new: CallState
    ) -> bool:
        occ = self.occurrences.get(occurrence_id)
        if occ is None or occ.state not in expected:
            return False
        occ.state = new
        occ.updated_at = self._now()
        return True

    async def occurrences_in_state(
        self, state: CallState, updated_before: datetime
    ) -> list[CallOccurrence]:
        return [
            o
            for o in self.occurrences.values()
            if o.state is state and o.updated_at <= updated_before
        ]

    async def cancel_future_occurrences(self, schedule_id: uuid.UUID) -> int:
        count = 0
        for occ in self.occurrences.values():
            if occ.schedule_id == schedule_id and occ.state is CallState.SCHEDULED:
                occ.state = CallState.CANCELLED
                occ.updated_at = self._now()
                count += 1
        return count

    # ── attempts ──
    async def add_attempt(
        self,
        *,
        occurrence_id: uuid.UUID,
        channel: CallChannelKind,
        previous_attempt_id: uuid.UUID | None = None,
    ) -> CallAttempt:
        now = self._now()
        number = len([a for a in self.attempts.values() if a.occurrence_id == occurrence_id]) + 1
        row = CallAttempt(
            id=uuid.uuid4(),
            occurrence_id=occurrence_id,
            attempt_no=number,
            previous_attempt_id=previous_attempt_id,
            channel=channel,
            state=CallState.QUEUED,
            created_at=now,
            updated_at=now,
        )
        self.attempts[row.id] = row
        return row

    async def get_attempt(self, attempt_id: uuid.UUID) -> CallAttempt | None:
        return self.attempts.get(attempt_id)

    async def attempts_for_occurrence(self, occurrence_id: uuid.UUID) -> list[CallAttempt]:
        return sorted(
            (a for a in self.attempts.values() if a.occurrence_id == occurrence_id),
            key=lambda a: a.attempt_no,
        )

    async def attempt_by_conversation(self, conversation_id: str) -> CallAttempt | None:
        for attempt in self.attempts.values():
            if attempt.el_conversation_id == conversation_id:
                return attempt
        return None

    async def transition_attempt(
        self,
        attempt_id: uuid.UUID,
        expected: Collection[CallState],
        new: CallState,
        **fields: Any,
    ) -> bool:
        attempt = self.attempts.get(attempt_id)
        if attempt is None or attempt.state not in expected:
            return False
        attempt.state = new
        for key, value in fields.items():
            setattr(attempt, key, value)
        attempt.updated_at = self._now()
        return True

    async def update_attempt(self, attempt_id: uuid.UUID, **fields: Any) -> None:
        attempt = self.attempts[attempt_id]
        for key, value in fields.items():
            setattr(attempt, key, value)
        attempt.updated_at = self._now()

    async def attempts_in_state(
        self, state: CallState, updated_before: datetime
    ) -> list[CallAttempt]:
        return [
            a for a in self.attempts.values() if a.state is state and a.updated_at <= updated_before
        ]

    async def active_attempt_count(self) -> int:
        return sum(1 for a in self.attempts.values() if a.state in ACTIVE)

    async def ringing_attempt_for_user(self, user_id: uuid.UUID) -> CallAttempt | None:
        ringing = [
            a
            for a in self.attempts.values()
            if a.state is CallState.RINGING
            and (occ := self.occurrences.get(a.occurrence_id)) is not None
            and occ.user_id == user_id
        ]
        return max(ringing, key=lambda a: a.created_at, default=None)

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
        row = self.push.get(endpoint)
        if row is None:
            row = PushSubscription(
                id=uuid.uuid4(),
                user_id=user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
                created_at=self._now(),
            )
            self.push[endpoint] = row
        row.user_id, row.p256dh, row.auth, row.revoked_at = user_id, p256dh, auth, None
        return row

    async def list_push_subscriptions(self, user_id: uuid.UUID) -> list[PushSubscription]:
        return [p for p in self.push.values() if p.user_id == user_id and p.revoked_at is None]

    async def revoke_push_subscription(self, endpoint: str) -> None:
        row = self.push.get(endpoint)
        if row is not None:
            row.revoked_at = self._now()
