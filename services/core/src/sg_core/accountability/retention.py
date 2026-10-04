"""Retention calls: each Bhima call ends with one spaced-repetition question on a due concept.

This module picks the concept and records which one was asked. It does not judge: the learner's
answer is in the call transcript, which the post-call judge pipeline (C11) turns into retention
evidence through the rules engine, so a blossom blooms or a plant wilts only from judged
evidence. C11 finds what was asked via the `retention_check` memory written here (`data` has
`concept_key`, `attempt_id`, `source="retention_call"`). Habit completion never counts as
technical evidence: nothing in `commitments` feeds this path.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_core.memory import MemoryStore, NewMemory
from sg_core.models.curriculum import Concept
from sg_core.models.enums import Character, MemoryLayer, MemorySource, MemoryStatus, PlantStatus
from sg_core.models.evidence import PlantState
from sg_core.models.memory import Memory

RETENTION_KIND = "retention_check"
RETENTION_SOURCE = "retention_call"
# Do not ask about the same concept again within this window.
REASK_AFTER = timedelta(days=3)


@dataclass(frozen=True, slots=True)
class DueConcept:
    key: str
    title: str
    status: str = "due"


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    concept_key: str
    title: str

    def dynamic_variables(self) -> dict[str, str]:
        return retention_variables(self)


def retention_variables(plan: RetentionPlan | None) -> dict[str, str]:
    """Agent dynamic variables; "none" tells Bhima to skip the retention question."""
    if plan is None:
        return {"retention_concept": "none", "retention_concept_title": "none"}
    return {"retention_concept": plan.concept_key, "retention_concept_title": plan.title}


def choose_retention_concept(
    due: Sequence[DueConcept], recently_asked: set[str]
) -> RetentionPlan | None:
    """Wilting concepts first, then the longest overdue (`due` is already soonest-first)."""
    fresh = [c for c in due if c.key not in recently_asked]
    fresh.sort(key=lambda c: c.status != PlantStatus.WILTING.value)  # stable: keeps order
    return RetentionPlan(fresh[0].key, fresh[0].title) if fresh else None


class RetentionSource(Protocol):
    async def due_concepts(self, user_id: uuid.UUID) -> list[DueConcept]: ...
    async def recently_asked(self, user_id: uuid.UUID, since: datetime) -> set[str]: ...
    async def record_request(
        self, user_id: uuid.UUID, plan: RetentionPlan, attempt_id: uuid.UUID
    ) -> None: ...


class InMemoryRetentionSource:
    def __init__(self, due: Sequence[DueConcept] = ()) -> None:
        self.due = list(due)
        self.asked: list[tuple[uuid.UUID, str, uuid.UUID, datetime]] = []

    async def due_concepts(self, user_id: uuid.UUID) -> list[DueConcept]:
        return list(self.due)

    async def recently_asked(self, user_id: uuid.UUID, since: datetime) -> set[str]:
        return {key for uid, key, _, at in self.asked if uid == user_id and at >= since}

    async def record_request(
        self, user_id: uuid.UUID, plan: RetentionPlan, attempt_id: uuid.UUID
    ) -> None:
        self.asked.append((user_id, plan.concept_key, attempt_id, datetime.now(UTC)))


class DbRetentionSource:
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        self._maker = maker

    async def due_concepts(self, user_id: uuid.UUID) -> list[DueConcept]:
        now = datetime.now(UTC)
        async with self._maker() as s:
            rows = (
                await s.execute(
                    select(Concept.key, Concept.title, PlantState.status)
                    .join(PlantState, PlantState.concept_id == Concept.id)
                    .where(
                        PlantState.user_id == user_id,
                        or_(
                            PlantState.status.in_(
                                [PlantStatus.DUE.value, PlantStatus.WILTING.value]
                            ),
                            PlantState.next_review_at <= now,
                        ),
                    )
                    .order_by(PlantState.next_review_at.asc().nulls_last())
                    .limit(8)
                )
            ).all()
        return [DueConcept(r.key, r.title, r.status.value) for r in rows]

    async def recently_asked(self, user_id: uuid.UUID, since: datetime) -> set[str]:
        async with self._maker() as s:
            rows = await s.scalars(
                select(Memory.data).where(
                    Memory.user_id == user_id,
                    Memory.kind == RETENTION_KIND,
                    Memory.created_at >= since,
                )
            )
            return {d["concept_key"] for d in rows if isinstance(d, dict) and "concept_key" in d}

    async def record_request(
        self, user_id: uuid.UUID, plan: RetentionPlan, attempt_id: uuid.UUID
    ) -> None:
        async with self._maker() as s, s.begin():
            await MemoryStore(s).append(
                NewMemory(
                    user_id=user_id,
                    layer=MemoryLayer.SESSION,
                    kind=RETENTION_KIND,
                    content=f"Bhima asked a retention question on {plan.title}.",
                    source=MemorySource.SYSTEM,
                    source_character=Character.BHIMA,
                    status=MemoryStatus.ACCEPTED,
                    visible_to=["bhima"],
                    data={
                        "concept_key": plan.concept_key,
                        "attempt_id": str(attempt_id),
                        "source": RETENTION_SOURCE,
                    },
                )
            )


async def plan_retention(
    source: RetentionSource, user_id: uuid.UUID, now: datetime | None = None
) -> RetentionPlan | None:
    now = now or datetime.now(UTC)
    due = await source.due_concepts(user_id)
    if not due:
        return None
    return choose_retention_concept(due, await source.recently_asked(user_id, now - REASK_AFTER))
